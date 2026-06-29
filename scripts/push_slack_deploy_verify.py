#!/usr/bin/env python3
"""Deploy verify: push 2 Slack messages via interactive Block Kit channel only.

1. Single real-time CRITICAL alert (Ack/Snooze buttons)
2. Daily briefing — clean B0FIXTURE01/02 + chart/PDF blocks
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

from amazon_mcp.integrations.slack_interactions import slack_interactive_enabled
from amazon_mcp.monitor.alert_store import AlertStore, get_default_alert_db_path
from amazon_mcp.monitor.notifier import get_router
from amazon_mcp.monitor.thresholds import AlertRecord, InventoryThreshold
from amazon_mcp.scenarios.daily_briefing import execute_daily_briefing
from amazon_mcp.server import _ctx, category_competitor_insights


async def main() -> int:
    if os.environ.get("NOTIFY_SLACK_ENABLED", "0") != "1":
        print(json.dumps({"ok": False, "error": "NOTIFY_SLACK_ENABLED must be 1"}))
        return 1
    if not slack_interactive_enabled():
        print(json.dumps({"ok": False, "error": "AMAZON_MCP_SLACK_INTERACTIVE_ENABLED must be 1 (plain channel closed)"}))
        return 1
    if not os.environ.get("NOTIFY_SLACK_WEBHOOK_URL", "").strip():
        print(json.dumps({"ok": False, "error": "NOTIFY_SLACK_WEBHOOK_URL missing"}))
        return 1

    router = get_router()
    results: dict = {"ok": True, "messages": []}

    # ── Message 1: single real-time alert (interactive blocks) ──
    alert = AlertRecord(
        alert_type="LOW_INVENTORY",
        severity="CRITICAL",
        title="[Deploy Verify] Single alert — B0FIXTURE01 low stock",
        detail="Fulfillable 8 < threshold 20. This is a deploy verification push.",
        asin="B0FIXTURE01",
        sku="SKU-FIX-001",
        data={"qty": 8, "threshold": 20, "deploy_verify": True},
    )
    AlertStore(get_default_alert_db_path()).add_alert(alert)
    r1 = await router.route(alert)
    results["messages"].append({"type": "single_realtime_alert", "channels": r1, "ok": r1.get("slack", False)})

    # ── Message 2: daily briefing — fixed 2 fixture ASINs ──
    db = str(ROOT / "data" / "alerts_deploy_verify.db")
    store = AlertStore(db_path=db)
    for p in Path(db).parent.glob("alerts_deploy_verify.db*"):
        try:
            p.unlink()
        except OSError:
            pass
    store = AlertStore(db_path=db)
    store.upsert_inventory_threshold(InventoryThreshold("SKU-FIX-001", "B0FIXTURE01", 20))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-FIX-002", "B0FIXTURE02", 50))

    cfg, sp, ads = _ctx()

    async def _insights(asin: str) -> dict:
        try:
            raw = await category_competitor_insights(asin)
            return json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    briefing = await execute_daily_briefing(
        alert_store=store,
        sp=sp,
        ads=ads,
        category_insights_fn=_insights,
        dry_run=cfg.dry_run,
        params={"notify_slack": True, "generate_assets": True, "asins": "B0FIXTURE01,B0FIXTURE02"},
    )
    r2 = briefing.get("notification", {}).get("channels", {})
    results["messages"].append({
        "type": "daily_briefing_fixed_2_asins",
        "channels": r2,
        "ok": r2.get("slack", False),
        "summary": briefing.get("summary"),
        "chart_url": (briefing.get("briefing_assets") or {}).get("chart_url"),
    })

    results["all_ok"] = all(m.get("ok") for m in results["messages"])
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if results["all_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
