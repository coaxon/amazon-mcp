"""Wire ToolDeps from server runtime into domain registry."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from amazon_mcp.tools.deps import ToolDeps, set_tool_deps
from amazon_mcp.tools.registry import bootstrap_domains


def init_tool_registry(
    *,
    ctx: Callable[[str], tuple[Any, Any, Any]],
    sp_call: Callable[[Awaitable[Any], str], Awaitable[str]],
    json_dumps: Callable[[Any], str],
    last_ctx_hit: Callable[[], bool],
    registered_tool_names: Callable[[], list[str]],
    server_start_time: float,
    alert_engine_getter: Callable[[], Any | None],
    get_store: Callable[[str], Any],
    get_cogs_store: Callable[[str], Any],
    ensure_default_tenant: Callable[[], None],
    version: str,
    scoring_version: str,
) -> None:
    set_tool_deps(ToolDeps(
        ctx=ctx,
        sp_call=sp_call,
        json_dumps=json_dumps,
        last_ctx_hit=last_ctx_hit,
        registered_tool_names=registered_tool_names,
        server_start_time=server_start_time,
        alert_engine_getter=alert_engine_getter,
        get_store=get_store,
        get_cogs_store=get_cogs_store,
        ensure_default_tenant=ensure_default_tenant,
        version=version,
        scoring_version=scoring_version,
    ))
    bootstrap_domains()
