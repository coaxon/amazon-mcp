#!/usr/bin/env python3
"""Acceptance C (Cursor) — wire-level MCP stdio probe for amazon-sp."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

RUN_MCP = ROOT / "run_mcp.sh"
PROMPT_ZH = "列出我的库存中所有 ASIN"


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=str(RUN_MCP),
        args=[],
        env={"AMAZON_MCP_DRY_RUN": "1"},
    )


def _text_from_result(result) -> str:
    parts: list[str] = []
    for block in result.content or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "\n".join(parts).strip()


async def probe(*, timeout: float = 20.0) -> dict:
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=timeout)
            tools = await asyncio.wait_for(session.list_tools(), timeout=timeout)
            names = sorted(t.name for t in tools.tools)

            health = await asyncio.wait_for(
                session.call_tool("amazon_health", {}), timeout=timeout
            )
            inventory = await asyncio.wait_for(
                session.call_tool("list_inventory_asins", {}), timeout=timeout
            )

            health_json = json.loads(_text_from_result(health))
            inv_json = json.loads(_text_from_result(inventory))
            return {
                "tools": names,
                "health": health_json,
                "inventory": inv_json,
            }


def main() -> int:
    print("=== Acceptance C: Cursor MCP (amazon-sp) ===")
    print(f"server: {RUN_MCP}")
    print(f"prompt: 「{PROMPT_ZH}」 → tool list_inventory_asins")

    out = asyncio.run(probe())
    names = out["tools"]
    inv = out["inventory"]

    print(f"tools_count={len(names)}")
    print(f"  tools: {', '.join(names)}")
    print(f"  health.dry_run={out['health'].get('dry_run')}")
    print(f"  inventory.asins={inv.get('asins')}")

    assert "list_inventory_asins" in names, "missing list_inventory_asins tool"
    assert inv.get("ok") is True, inv
    assert inv.get("asins") == ["B0FIXTURE01", "B0FIXTURE02"], inv

    print("\nC-RESULT: PASS (Cursor wire probe — list_inventory_asins OK)")
    print("Next: reload MCP in Cursor (Settings → MCP → amazon-sp enabled)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
