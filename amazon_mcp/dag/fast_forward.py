from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

_RUNTIME_DIR = Path(os.environ.get("AMAZON_MCP_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))) / ".runtime"


def _cp_path(plan_id: str) -> Path:
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return _RUNTIME_DIR / f"dag_{plan_id}.json"


class FastForward:
    """Checkpoint-based resume protocol for DAG execution."""

    @staticmethod
    def _atomic_write(path: Path, data: dict) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        tmp.replace(path)

    @staticmethod
    def save_root(plan_id: str, operation: str, params: dict) -> None:
        path = _cp_path(plan_id)
        state: dict = {}
        if path.exists():
            try:
                state = json.loads(path.read_text())
            except Exception:
                state = {}
        state["plan_id"] = plan_id
        state["operation"] = operation
        state["params"] = params
        FastForward._atomic_write(path, state)

    @staticmethod
    def save_checkpoint(plan_id: str, phase: str, result: Any) -> None:
        path = _cp_path(plan_id)
        state: dict = {}
        if path.exists():
            try:
                state = json.loads(path.read_text())
            except Exception:
                state = {}
        state.setdefault("plan_id", plan_id)
        state.setdefault("phases", {})
        state["phases"][phase] = {"result": result, "status": "done"}
        FastForward._atomic_write(path, state)

    @staticmethod
    def load_checkpoint(plan_id: str) -> Optional[dict]:
        path = _cp_path(plan_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    @staticmethod
    def get_completed_phases(plan_id: str) -> set[str]:
        state = FastForward.load_checkpoint(plan_id)
        if not state:
            return set()
        return {
            phase
            for phase, data in state.get("phases", {}).items()
            if isinstance(data, dict) and data.get("status") == "done"
        }

    @staticmethod
    def clear(plan_id: str) -> None:
        path = _cp_path(plan_id)
        if path.exists():
            path.unlink()

    @staticmethod
    def purge_old(max_age_seconds: int = 86400) -> int:
        import time
        cutoff = time.time() - max_age_seconds
        removed = 0
        for f in _RUNTIME_DIR.glob("dag_*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except Exception:
                pass
        return removed
