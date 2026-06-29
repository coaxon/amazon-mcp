#!/usr/bin/env python3
"""Acceptance C — Claude Desktop integration checklist + config validator."""
from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "claude_desktop_config.example.json"

PROMPT_ZH = "列出我的库存中所有 ASIN"
PROMPT_EN = "List all ASINs in my inventory"


def claude_config_paths() -> list[Path]:
    home = Path.home()
    if platform.system() == "Darwin":
        return [home / "Library/Application Support/Claude/claude_desktop_config.json"]
    if platform.system() == "Windows":
        return [Path(os.environ.get("APPDATA", "")) / "Claude/claude_desktop_config.json"]
    return [home / ".config/Claude/claude_desktop_config.json"]


def validate_mcp_entry(entry: dict) -> list[str]:
    issues: list[str] = []
    cmd = str(entry.get("command") or "")
    cwd = str(entry.get("cwd") or "")
    if "amazon-mcp" not in cmd and "amazon-mcp" not in cwd:
        issues.append("command/cwd should reference products/amazon-mcp (wrong working directory causes fake-no-module)")
    if not cmd:
        issues.append("missing command")
    return issues


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--check-config", action="store_true")
    p.add_argument("--print-config", action="store_true")
    args = p.parse_args()

    suggested = {
        "mcpServers": {
            "amazon-sp": {
                "command": str(ROOT / "run_mcp.sh"),
                "args": [],
                "env": {"AMAZON_MCP_DRY_RUN": "1"},
            }
        }
    }

    if args.print_config:
        print(json.dumps(suggested, indent=2, ensure_ascii=False))
        return 0

    print("=== Acceptance C: Claude Desktop Integration ===")
    print("1. Merge MCP config (use --print-config for snippet)")
    print("2. Restart Claude Desktop")
    print(f'3. Ask Claude: 「{PROMPT_ZH}」 or "{PROMPT_EN}"')
    print("4. Expect tool call: list_inventory_asins")
    print("5. Expect ASINs: B0FIXTURE01, B0FIXTURE02 (dry-run)")

    found = False
    for cfg_path in claude_config_paths():
        if not cfg_path.is_file():
            continue
        found = True
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers") or {}
        amazon = servers.get("amazon-sp") or servers.get("amazon_mcp")
        if not amazon:
            print(f"  WARN: {cfg_path} has no amazon-sp server entry")
            print("  C-RESULT: MANUAL — add config then retest")
            return 0
        issues = validate_mcp_entry(amazon)
        if issues:
            for i in issues:
                print(f"  WARN: {i}")
            print("  C-RESULT: MANUAL — fix config issues above")
            return 0
        print(f"  OK: found amazon-sp in {cfg_path}")
        print("  C-RESULT: CONFIG OK — complete manual chat test in Claude Desktop")
        return 0

    if not found:
        print("  Claude config not found on this machine.")
        print(f"  Example: {EXAMPLE}")
        print("  C-RESULT: MANUAL — install config, then run chat test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
