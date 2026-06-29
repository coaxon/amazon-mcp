from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .fast_forward import FastForward

logger = logging.getLogger(__name__)

_AUDIT_LOG_DIR = Path(os.environ.get("AMAZON_MCP_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))) / "dag_logs"


class DagPhase(str, Enum):
    PLAN = "PLAN"
    EXEC = "EXEC"
    AUDIT = "AUDIT"


@dataclass
class DagState:
    plan_id: str
    operation: str
    params: dict
    phases: dict = field(default_factory=dict)
    status: str = "pending"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class DagExecutor:
    """Executes SP-API calls through [PLAN] -> [EXEC] -> [AUDIT] three-phase DAG."""

    def __init__(self, sp_client: Any = None, dry_run: bool = False):
        self.sp = sp_client
        self.dry_run = dry_run
        self._ff = FastForward()

    def _audit_log(self, plan_id: str, entry: dict) -> None:
        _AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _AUDIT_LOG_DIR / f"dag_audit_{plan_id}.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps({**entry, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")

    async def _run_phase_plan(self, operation: str, params: dict) -> dict:
        supported = {
            "get_catalog_item", "search_catalog", "get_product_pricing",
            "get_competitive_pricing", "get_inventory_summaries",
            "list_orders", "get_financial_events", "create_fba_inbound_plan",
        }
        if operation not in supported and not self.dry_run:
            raise ValueError(f"Unsupported operation '{operation}'. Supported: {sorted(supported)}")
        return {
            "operation": operation,
            "params_validated": True,
            "estimated_api_calls": 1,
            "supported_operations": sorted(supported),
        }

    async def _run_phase_exec(self, operation: str, params: dict) -> dict:
        if self.dry_run or self.sp is None:
            return {"dry_run": True, "operation": operation, "simulated": True, "data": {}}
        method = getattr(self.sp, operation, None)
        if method is None:
            raise ValueError(f"SP-API client has no method '{operation}'")
        result = await method(**params)
        return result if isinstance(result, dict) else {"raw": result}

    def _run_phase_audit(self, plan_id: str, operation: str, exec_result: dict) -> dict:
        try:
            from amazon_mcp.refiner.dom_refiner import (
                refine_product, refine_inventory, refine_pricing,
                refine_order_summary, refine_competitive,
            )
            refiner_map = {
                "get_catalog_item": refine_product,
                "search_catalog": lambda r: {"items": [refine_product(i) for i in r.get("items", [])]},
                "get_product_pricing": refine_pricing,
                "get_competitive_pricing": refine_competitive,
                "get_inventory_summaries": refine_inventory,
                "list_orders": refine_order_summary,
            }
            refined = refiner_map.get(operation, lambda x: x)(exec_result)
        except Exception:
            refined = exec_result

        return {
            "plan_id": plan_id,
            "operation": operation,
            "refined": refined,
            "audit_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    async def execute_plan_only(self, plan_id: str, operation: str, params: dict) -> DagState:
        """Run PLAN phase only (read-only validation / preview)."""
        state = DagState(plan_id=plan_id, operation=operation, params=params)
        result = await self._run_phase_plan(operation, params)
        state.phases[DagPhase.PLAN.value] = {"result": result, "status": "done"}
        state.status = "plan_complete"
        state.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._audit_log(plan_id, {"phase": "PLAN", "operation": operation, "result": result})
        return state

    async def execute(self, plan_id: str, operation: str, params: dict) -> DagState:
        state = DagState(plan_id=plan_id, operation=operation, params=params)
        FastForward.save_root(plan_id, operation, params)
        completed = FastForward.get_completed_phases(plan_id)

        for phase in [DagPhase.PLAN, DagPhase.EXEC, DagPhase.AUDIT]:
            if phase.value in completed:
                state.phases[phase.value] = FastForward.load_checkpoint(plan_id)["phases"][phase.value]
                logger.info(f"[DAG] FastForward: skipping completed phase {phase.value}")
                continue

            try:
                if phase == DagPhase.PLAN:
                    result = await self._run_phase_plan(operation, params)
                elif phase == DagPhase.EXEC:
                    result = await self._run_phase_exec(operation, params)
                else:
                    exec_result = state.phases.get(DagPhase.EXEC.value, {}).get("result", {})
                    result = self._run_phase_audit(plan_id, operation, exec_result)

                state.phases[phase.value] = {"result": result, "status": "done"}
                FastForward.save_checkpoint(plan_id, phase.value, result)
                self._audit_log(plan_id, {"plan_id": plan_id, "phase": phase.value, "status": "done"})

            except Exception as e:
                state.phases[phase.value] = {"status": "failed", "error": str(e)}
                state.status = "failed"
                self._audit_log(plan_id, {"plan_id": plan_id, "phase": phase.value, "status": "failed", "error": str(e)})
                return state

        state.status = "complete"
        state.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return state

    async def resume(self, plan_id: str) -> DagState:
        checkpoint = FastForward.load_checkpoint(plan_id)
        if not checkpoint:
            raise ValueError(f"No checkpoint found for plan_id='{plan_id}'")
        operation = (
            checkpoint.get("operation")
            or checkpoint.get("phases", {}).get("PLAN", {}).get("result", {}).get("operation")
            or "unknown"
        )
        params = checkpoint.get("params", {})
        return await self.execute(plan_id, operation, params)
