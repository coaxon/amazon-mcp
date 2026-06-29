#!/usr/bin/env python3
"""Run Pause Ad Preview → Confirm flow (dry-run) — mirrors Slack button clicks."""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
from typing import Any
from unittest.mock import patch
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

def _confirm_value_from_blocks(blocks):
    for block in blocks:
        if block.get("type") != "actions":
            continue
        for el in block.get("elements", []):
            if el.get("action_id") == "confirm_pause_campaign":
                return str(el.get("value") or "")
    raise RuntimeError("confirm_pause_campaign not found")

async def main():
    import os
    os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")
    import amazon_mcp.server as srv
    if srv._slack_interaction_handler._pause_ad_service is None:
        srv._attach_pause_ad_service()
    handler = srv._slack_interaction_handler
    reason = "Inventory cover 0.7d < 7.0d threshold AND ACoS 22.0% < healthy ceiling 25% AND ad status watch"
    preview_value = json.dumps({"action_type": "preview_pause_campaign", "rule_id": "pause_ads_low_cover", "reason": reason}, separators=(",", ":"))
    captured = []
    async def capture_post(_url, message):
        captured.append(message)
    preview_payload = {
        "type": "block_actions",
        "user": {"id": "U_CEO", "username": "ceo"},
        "response_url": "https://capture.local/preview",
        "message": {"blocks": [{"type": "actions", "block_id": "pause_ad_preview_pause_ads_low_cover", "elements": [{"action_id": "preview_pause_campaign", "value": preview_value}]}]},
        "actions": [{"action_id": "preview_pause_campaign", "block_id": "pause_ad_preview_pause_ads_low_cover", "value": preview_value}],
    }
    with patch("amazon_mcp.integrations.slack_interactions.post_response_url", side_effect=capture_post):
        await handler.handle_payload(preview_payload)
    preview_blocks = captured[-1]["blocks"]
    preview_text = preview_blocks[0]["text"]["text"]
    confirm_value = _confirm_value_from_blocks(preview_blocks)
    confirm_payload = {
        "type": "block_actions",
        "user": {"id": "U_CEO", "username": "ceo"},
        "response_url": "https://capture.local/confirm",
        "message": {"blocks": preview_blocks},
        "actions": [{"action_id": "confirm_pause_campaign", "block_id": "pause_ad_confirm_pause_ads_low_cover", "value": confirm_value}],
    }
    with patch("amazon_mcp.integrations.slack_interactions.post_response_url", side_effect=capture_post):
        await handler.handle_payload(confirm_payload)
    confirm_text = captured[-1]["blocks"][0]["text"]["text"]
    pa = _ROOT / "data" / "pause_ad_preview_audit.jsonl"
    ca = _ROOT / "data" / "pause_ad_audit.jsonl"
    print(json.dumps({"ok": True, "preview_has_confirm_button": "Confirm Pause" in json.dumps(preview_blocks), "preview_excerpt": preview_text[:500], "confirm_message": confirm_text, "preview_audit_tail": pa.read_text().strip().splitlines()[-1] if pa.is_file() else "", "confirm_audit_tail": ca.read_text().strip().splitlines()[-1] if ca.is_file() else ""}, indent=2))
    return 0
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
