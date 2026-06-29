"""Tests for P4.3 sync_schedule domain — scheduling layer + manual trigger + history."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")


@pytest.fixture(autouse=True)
def _bootstrap():
    import amazon_mcp.server  # noqa: F401
    yield


@pytest.fixture(autouse=True)
def _patch_files(tmp_path, monkeypatch):
    """Isolate schedule + history files per test."""
    import amazon_mcp.tools.sync_schedule as ss_mod
    monkeypatch.setattr(ss_mod, "_SCHEDULE_FILE", tmp_path / "sync_schedules.json")
    monkeypatch.setattr(ss_mod, "_HISTORY_FILE", tmp_path / "sync_history.jsonl")
    monkeypatch.setattr(ss_mod, "_DATA_DIR", tmp_path)
    yield


from amazon_mcp.tools.sync_schedule import (
    create_schedule,
    delete_schedule,
    list_schedules,
    sync_history,
    trigger_now,
    real_time_sync_info,
    connection_status,
)
from amazon_mcp.tools.registry import dispatch_domain


# ── create_schedule ───────────────────────────────────────────────────────────

class TestCreateSchedule:
    @pytest.mark.asyncio
    async def test_create_returns_ok(self):
        result = await create_schedule({"tenant_id": "default", "label": "Test schedule"})
        assert result["ok"] is True
        assert result["action"] in ("created", "updated")

    @pytest.mark.asyncio
    async def test_schedule_id_in_result(self):
        result = await create_schedule({"tenant_id": "default", "schedule_id": "my_sched"})
        assert result["schedule_id"] == "my_sched"

    @pytest.mark.asyncio
    async def test_create_then_update(self):
        await create_schedule({"tenant_id": "default", "schedule_id": "s1", "label": "v1"})
        result = await create_schedule({"tenant_id": "default", "schedule_id": "s1", "label": "v2"})
        assert result["action"] == "updated"
        assert result["schedule"]["label"] == "v2"

    @pytest.mark.asyncio
    async def test_schedule_has_config_fields(self):
        result = await create_schedule({
            "tenant_id": "default",
            "schedule_id": "s2",
            "platforms": "amazon,meli",
            "min_move_units": 10,
        })
        s = result["schedule"]
        assert s["platforms"] == "amazon,meli"
        assert s["min_move_units"] == 10


# ── list_schedules ────────────────────────────────────────────────────────────

class TestListSchedules:
    @pytest.mark.asyncio
    async def test_empty_list(self):
        result = await list_schedules({})
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["schedules"] == []

    @pytest.mark.asyncio
    async def test_list_after_create(self):
        await create_schedule({"schedule_id": "a"})
        await create_schedule({"schedule_id": "b"})
        result = await list_schedules({})
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_list_filter_by_tenant(self):
        await create_schedule({"tenant_id": "t1", "schedule_id": "s1"})
        await create_schedule({"tenant_id": "t2", "schedule_id": "s2"})
        result = await list_schedules({"tenant_id": "t1"})
        assert result["count"] == 1
        assert result["schedules"][0]["schedule_id"] == "s1"


# ── delete_schedule ───────────────────────────────────────────────────────────

class TestDeleteSchedule:
    @pytest.mark.asyncio
    async def test_delete_existing(self):
        await create_schedule({"schedule_id": "to_delete"})
        result = await delete_schedule({"schedule_id": "to_delete"})
        assert result["ok"] is True
        assert result["remaining_count"] == 0

    @pytest.mark.asyncio
    async def test_delete_missing_id(self):
        result = await delete_schedule({})
        assert result["ok"] is False
        assert "schedule_id" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        result = await delete_schedule({"schedule_id": "ghost"})
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_delete_reduces_count(self):
        await create_schedule({"schedule_id": "s1"})
        await create_schedule({"schedule_id": "s2"})
        await delete_schedule({"schedule_id": "s1"})
        result = await list_schedules({})
        assert result["count"] == 1


# ── trigger_now ───────────────────────────────────────────────────────────────

class TestTriggerNow:
    @pytest.mark.asyncio
    async def test_trigger_returns_ok(self):
        result = await trigger_now({"tenant_id": "default"})
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_trigger_has_ts(self):
        result = await trigger_now({})
        assert "trigger_ts" in result

    @pytest.mark.asyncio
    async def test_trigger_reconcile_result_present(self):
        result = await trigger_now({})
        assert "reconcile_result" in result
        assert result["reconcile_result"]["ok"] is True

    @pytest.mark.asyncio
    async def test_trigger_history_logged(self):
        await trigger_now({"tenant_id": "default"})
        hist = await sync_history({"tenant_id": "default"})
        assert hist["entry_count"] >= 1

    @pytest.mark.asyncio
    async def test_trigger_with_schedule_id(self):
        await create_schedule({"schedule_id": "sc1", "tenant_id": "default"})
        result = await trigger_now({"schedule_id": "sc1", "tenant_id": "default"})
        assert result["ok"] is True
        assert result["schedule_id"] == "sc1"

    @pytest.mark.asyncio
    async def test_trigger_dry_run_is_preview(self):
        result = await trigger_now({"tenant_id": "default", "confirm": True})
        rec = result["reconcile_result"]
        # In dry_run mode, always preview
        assert rec.get("preview_only") is True or rec.get("queued_count", 0) == 0


# ── sync_history ──────────────────────────────────────────────────────────────

class TestSyncHistory:
    @pytest.mark.asyncio
    async def test_empty_history(self):
        result = await sync_history({})
        assert result["ok"] is True
        assert result["entry_count"] == 0

    @pytest.mark.asyncio
    async def test_history_grows(self):
        await trigger_now({})
        await trigger_now({})
        result = await sync_history({"limit": 10})
        assert result["entry_count"] == 2

    @pytest.mark.asyncio
    async def test_history_entry_shape(self):
        await trigger_now({"tenant_id": "default"})
        result = await sync_history({"tenant_id": "default"})
        entry = result["entries"][0]
        for k in ("ts", "tenant_id", "schedule_id", "dry_run", "confirm"):
            assert k in entry, f"missing key: {k}"

    @pytest.mark.asyncio
    async def test_history_limit(self):
        for _ in range(5):
            await trigger_now({})
        result = await sync_history({"limit": 3})
        assert result["entry_count"] <= 3


# ── real_time_sync_info ───────────────────────────────────────────────────────

class TestRealTimeSyncInfo:
    @pytest.mark.asyncio
    async def test_returns_enterprise_info(self):
        result = await real_time_sync_info({})
        assert result["ok"] is True
        assert result["availability"] == "Enterprise SOW"

    @pytest.mark.asyncio
    async def test_has_current_and_enterprise_lists(self):
        result = await real_time_sync_info({})
        assert len(result["current_tier_includes"]) > 0
        assert len(result["enterprise_adds"]) > 0

    @pytest.mark.asyncio
    async def test_sales_hint_present(self):
        result = await real_time_sync_info({})
        assert "sales_hint" in result
        assert len(result["sales_hint"]) > 20


# ── connection_status ─────────────────────────────────────────────────────────

class TestConnectionStatus:
    @pytest.mark.asyncio
    async def test_phase_p43(self):
        result = await connection_status({})
        assert result["ok"] is True
        assert result["phase"] == "P4.3"

    @pytest.mark.asyncio
    async def test_roadmap_p43_complete(self):
        result = await connection_status({})
        assert "P4.3" in result["roadmap"]
        assert "✅" in result["roadmap"]["P4.3"]

    @pytest.mark.asyncio
    async def test_has_last_run_when_triggered(self):
        await trigger_now({"tenant_id": "default"})
        result = await connection_status({"tenant_id": "default"})
        # last_run may be present
        assert result["recent_runs"] >= 1


# ── Domain dispatch ───────────────────────────────────────────────────────────

class TestSyncScheduleDomain:
    @pytest.mark.asyncio
    async def test_create_via_dispatch(self):
        raw = await dispatch_domain("sync_schedule", "create_schedule", {
            "schedule_id": "test_sched", "label": "dispatch test"
        })
        data = json.loads(raw)
        assert data["ok"] is True
        assert data["domain"] == "amazon_sync_schedule"

    @pytest.mark.asyncio
    async def test_list_via_dispatch(self):
        raw = await dispatch_domain("sync_schedule", "list_schedules", {})
        data = json.loads(raw)
        assert data["ok"] is True
        assert "schedules" in data["data"]

    @pytest.mark.asyncio
    async def test_trigger_via_dispatch(self):
        raw = await dispatch_domain("sync_schedule", "trigger_now", {"confirm": False})
        data = json.loads(raw)
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_real_time_info_via_dispatch(self):
        raw = await dispatch_domain("sync_schedule", "real_time_sync_info", {})
        data = json.loads(raw)
        assert data["ok"] is True
        assert data["data"]["availability"] == "Enterprise SOW"

    @pytest.mark.asyncio
    async def test_connection_status_via_dispatch(self):
        raw = await dispatch_domain("sync_schedule", "connection_status", {})
        data = json.loads(raw)
        assert data["ok"] is True
        assert data["data"]["phase"] == "P4.3"

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        raw = await dispatch_domain("sync_schedule", "no_such_action", {})
        data = json.loads(raw)
        assert data["ok"] is False


# ── Feature gate ───────────────────────────────────────────────────────────────

class TestSyncScheduleFeatureGate:
    @pytest.mark.asyncio
    async def test_passes_for_default_tenant(self):
        raw = await dispatch_domain("sync_schedule", "connection_status", {"tenant_id": "default"})
        data = json.loads(raw)
        assert data["ok"] is True
        assert "feature_disabled" not in data.get("data", {})

    @pytest.mark.asyncio
    async def test_in_feature_registry(self):
        from amazon_mcp.features.feature_registry import FEATURES_BY_ID
        feat = FEATURES_BY_ID.get("feat.sync_schedule")
        assert feat is not None
        assert feat.tier_min == "global_suite"

    @pytest.mark.asyncio
    async def test_in_global_suite(self):
        from amazon_mcp.features.tier_bundles import GLOBAL_SUITE
        assert "feat.sync_schedule" in GLOBAL_SUITE

    @pytest.mark.asyncio
    async def test_not_in_standard(self):
        from amazon_mcp.features.tier_bundles import STANDARD
        assert "feat.sync_schedule" not in STANDARD
