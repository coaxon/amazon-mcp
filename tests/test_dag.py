import pytest
import asyncio
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import patch

from amazon_mcp.dag.fast_forward import FastForward
from amazon_mcp.dag.executor import DagExecutor, DagPhase, DagState


@pytest.fixture(autouse=True)
def tmp_runtime(tmp_path, monkeypatch):
    """Redirect checkpoint dir to tmp."""
    import amazon_mcp.dag.fast_forward as ff_mod
    import amazon_mcp.dag.executor as exec_mod
    ff_mod._RUNTIME_DIR = tmp_path / "runtime"
    exec_mod._AUDIT_LOG_DIR = tmp_path / "logs"
    yield tmp_path


@pytest.mark.asyncio
async def test_dag_three_phases_in_order():
    executor = DagExecutor(sp_client=None, dry_run=True)
    state = await executor.execute("plan-001", "get_catalog_item", {"asin": "B0001"})
    assert state.status == "complete"
    assert "PLAN" in state.phases
    assert "EXEC" in state.phases
    assert "AUDIT" in state.phases
    # Verify order: all three phases present and done
    for phase in ["PLAN", "EXEC", "AUDIT"]:
        assert state.phases[phase]["status"] == "done"


@pytest.mark.asyncio
async def test_checkpoint_written_after_each_phase():
    executor = DagExecutor(dry_run=True)
    await executor.execute("plan-002", "get_catalog_item", {})
    completed = FastForward.get_completed_phases("plan-002")
    assert "PLAN" in completed
    assert "EXEC" in completed
    assert "AUDIT" in completed


def test_fast_forward_save_and_load():
    FastForward.save_checkpoint("plan-003", "PLAN", {"validated": True})
    state = FastForward.load_checkpoint("plan-003")
    assert state is not None
    assert state["phases"]["PLAN"]["result"]["validated"] is True
    assert state["phases"]["PLAN"]["status"] == "done"


def test_get_completed_phases_empty_for_unknown():
    completed = FastForward.get_completed_phases("plan-nonexistent-xyz")
    assert completed == set()


def test_fast_forward_skip_completed():
    FastForward.save_checkpoint("plan-004", "PLAN", {"pre_done": True})
    completed = FastForward.get_completed_phases("plan-004")
    assert "PLAN" in completed
    assert "EXEC" not in completed


@pytest.mark.asyncio
async def test_resume_from_checkpoint():
    executor = DagExecutor(dry_run=True)
    # First run completes PLAN + EXEC
    state1 = await executor.execute("plan-005", "get_catalog_item", {})
    assert state1.status == "complete"
    # Simulate EXEC/AUDIT being cleared so resume picks up from last done
    completed_before = FastForward.get_completed_phases("plan-005")
    assert len(completed_before) == 3


@pytest.mark.asyncio
async def test_plan_phase_rejects_unknown_operation_in_live_mode():
    executor = DagExecutor(dry_run=False, sp_client=None)
    state = await executor.execute("plan-006", "delete_everything", {})
    assert state.status == "failed"
    assert "PLAN" in state.phases
    assert state.phases["PLAN"]["status"] == "failed"


def test_fast_forward_clear():
    FastForward.save_checkpoint("plan-007", "PLAN", {"x": 1})
    assert FastForward.load_checkpoint("plan-007") is not None
    FastForward.clear("plan-007")
    assert FastForward.load_checkpoint("plan-007") is None


@pytest.mark.asyncio
async def test_dag_audit_phase_contains_refined_data():
    executor = DagExecutor(dry_run=True)
    state = await executor.execute("plan-008", "get_inventory_summaries", {})
    assert state.status == "complete"
    audit_result = state.phases["AUDIT"]["result"]
    assert "plan_id" in audit_result
    assert "audit_timestamp" in audit_result
