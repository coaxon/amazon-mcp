#!/usr/bin/env python3
"""Acceptance A — Contract Compliance: all tools return valid JSON ToolResult payloads."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# AmazonMCP root on path
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")
import tempfile
os.environ.setdefault("AMAZON_COGS_DB_PATH", tempfile.mktemp(suffix="_mcp_acceptance_cogs.db"))

from amazon_mcp.server import TOOL_HANDLERS  # noqa: E402
import amazon_mcp.server as _srv  # noqa: E402
_srv._cogs_store_cache.clear()


def to_tool_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    """MCP ToolResult shape (Claude / MCP spec)."""
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def assert_valid_business_json(payload: dict[str, Any], tool_name: str) -> None:
    assert isinstance(payload, dict), f"{tool_name}: root must be object"
    assert "ok" in payload or "service" in payload or "error" in payload, (
        f"{tool_name}: missing ok/service/error field"
    )


def assert_tool_result_compliance(tool_name: str, raw: str) -> dict[str, Any]:
    tool_result = to_tool_result(raw)
    assert tool_result["content"], f"{tool_name}: empty content"
    assert tool_result["content"][0]["type"] == "text"
    text = tool_result["content"][0]["text"]
    assert isinstance(text, str) and text.strip(), f"{tool_name}: empty text"

    payload = json.loads(text)
    assert_valid_business_json(payload, tool_name)
    return {"tool": tool_name, "tool_result": tool_result, "payload": payload}


async def run_all_tools() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, factory in TOOL_HANDLERS.items():
        raw = await factory()
        results.append(assert_tool_result_compliance(name, raw))
    return results


def main() -> int:
    print("=== Acceptance A: Contract Compliance ===")
    print(f"tools={len(TOOL_HANDLERS)} dry_run={os.environ.get('AMAZON_MCP_DRY_RUN')}")
    results = asyncio.run(run_all_tools())
    for row in results:
        p = row["payload"]
        head = json.dumps(p, ensure_ascii=False)[:120]
        print(f"  PASS {row['tool']}: {head}...")
    print(f"\nA-RESULT: PASS ({len(results)}/{len(TOOL_HANDLERS)} tools, ToolResult JSON valid)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
