"""Shared helpers for domain tool handlers."""
from __future__ import annotations

import json
from typing import Any, Awaitable

from amazon_mcp.tools.deps import get_tool_deps


async def sp_json(coro: Awaitable[Any], tool: str = "") -> dict[str, Any]:
    deps = get_tool_deps()
    return json.loads(await deps.sp_call(coro, tool))
