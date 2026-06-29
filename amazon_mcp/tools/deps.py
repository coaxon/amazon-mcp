"""Injectable dependencies for domain tool handlers (wired from server.py)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")

DEFAULT_TENANT_ID = "default"


@dataclass
class ToolDeps:
    ctx: Callable[[str], tuple[Any, Any, Any]]
    sp_call: Callable[[Awaitable[Any], str], Awaitable[str]]
    json_dumps: Callable[[Any], str]
    last_ctx_hit: Callable[[], bool]
    registered_tool_names: Callable[[], list[str]]
    server_start_time: float = 0.0
    alert_engine_getter: Callable[[], Any | None] | None = None
    get_store: Callable[[str], Any] | None = None
    get_cogs_store: Callable[[str], Any] | None = None
    ensure_default_tenant: Callable[[], None] | None = None
    version: str = "0.1.0"
    scoring_version: str = "v1-weighted"


_deps: ToolDeps | None = None


def set_tool_deps(deps: ToolDeps) -> None:
    global _deps
    _deps = deps


def get_tool_deps() -> ToolDeps:
    if _deps is None:
        raise RuntimeError("ToolDeps not initialized — call set_tool_deps() from server.py")
    return _deps


def tenant_id_from_params(params: dict[str, Any] | None) -> str:
    raw = (params or {}).get("tenant_id", DEFAULT_TENANT_ID)
    tid = str(raw or DEFAULT_TENANT_ID).strip()
    tid = tid or DEFAULT_TENANT_ID
    if not _TENANT_ID_RE.match(tid):
        raise ValueError(f"Invalid tenant_id '{tid}' — must be 1-64 alphanumeric/underscore/dash characters")
    return tid


def ctx_from_params(params: dict[str, Any] | None) -> tuple[Any, Any, Any]:
    deps = get_tool_deps()
    tid = tenant_id_from_params(params)
    if deps.ensure_default_tenant:
        deps.ensure_default_tenant()
    return deps.ctx(tid)
