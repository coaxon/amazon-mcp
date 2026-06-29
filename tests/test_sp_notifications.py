"""SP-API Notifications — ANY_OFFER_CHANGED + FBA_INVENTORY_AVAILABILITY_CHANGES."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.auth.lwa import LWAAuth
from amazon_mcp.clients.rate_limit import RateLimitRegistry
from amazon_mcp.clients.sp_api import SPAPIClient
from amazon_mcp.config import AmazonConfig
from amazon_mcp.integrations.sp_notifications import (
    build_event_slack_snippet,
    evaluate_inventory_polling_replacement,
    evaluate_polling_replacement,
    format_trigger_reason,
    handle_any_offer_changed_webhook,
    handle_notification_webhook,
    parse_any_offer_changed,
    parse_fba_inventory_availability_changes,
    parse_notification_payload,
    reevaluate_cross_domain_rules_for_event,
)
from amazon_mcp.monitor.alert_store import AlertStore
from amazon_mcp.monitor.thresholds import InventoryThreshold
from amazon_mcp.scenarios.cross_domain_rules import build_rule_context
from fixtures.loader import load_fixture


@pytest.fixture
def dry_sp(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    cfg = AmazonConfig.from_env()
    auth = LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token)
    return SPAPIClient(cfg, auth, RateLimitRegistry())


def test_parse_any_offer_changed_fixture():
    payload = load_fixture("sp_api", "any_offer_changed_event.json")
    event = parse_any_offer_changed(payload)
    assert event["asin"] == "B0FIXTURE01"
    assert event["notification_type"] == "ANY_OFFER_CHANGED"


def test_parse_fba_inventory_availability_fixture():
    payload = load_fixture("sp_api", "fba_inventory_availability_changed_event.json")
    event = parse_fba_inventory_availability_changes(payload)
    assert event["asin"] == "B0FIXTURE01"
    assert event["previous_fulfillable_quantity"] == 120
    assert event["fulfillable_quantity"] == 8
    assert event["notification_type"] == "FBA_INVENTORY_AVAILABILITY_CHANGES"


def test_parse_notification_payload_dispatches_inventory():
    payload = load_fixture("sp_api", "fba_inventory_availability_changed_event.json")
    event = parse_notification_payload(payload)
    assert event["detected_type"] == "FBA_INVENTORY_AVAILABILITY_CHANGES"
    assert event["asin"] == "B0FIXTURE01"


def test_evaluate_polling_replacement_feasibility():
    ev = evaluate_polling_replacement({"asin": "B0FIXTURE01", "notification_type": "ANY_OFFER_CHANGED"})
    assert ev["feasibility"] == "viable_for_price_watches"
    assert ev["latency_improvement_s"] == 900


def test_evaluate_inventory_polling_replacement_feasibility():
    ev = evaluate_inventory_polling_replacement(
        {"asin": "B0FIXTURE01", "notification_type": "FBA_INVENTORY_AVAILABILITY_CHANGES"}
    )
    assert ev["feasibility"] == "viable_for_inventory_thresholds_and_reorder"
    assert ev["latency_improvement_s"] == 300


def test_format_trigger_reason_inventory_with_rule():
    event = parse_fba_inventory_availability_changes(
        load_fixture("sp_api", "fba_inventory_availability_changed_event.json")
    )
    reason = format_trigger_reason(event, rule_id="pause_ads_low_cover")
    assert "FBA_INVENTORY_AVAILABILITY_CHANGES" in reason
    assert "B0FIXTURE01" in reason
    assert "120→8" in reason
    assert "pause_ads_low_cover" in reason


@pytest.mark.asyncio
async def test_subscribe_any_offer_changed_dry_run(dry_sp):
    result = await dry_sp.subscribe_any_offer_changed("https://example.com/hook")
    assert result["ok"] is True
    assert result["notificationType"] == "ANY_OFFER_CHANGED"
    assert result["subscriptionId"]


@pytest.mark.asyncio
async def test_subscribe_fba_inventory_availability_dry_run(dry_sp):
    result = await dry_sp.subscribe_fba_inventory_availability_changes("https://example.com/hook")
    assert result["ok"] is True
    assert result["notificationType"] == "FBA_INVENTORY_AVAILABILITY_CHANGES"
    assert result["subscriptionId"]


@pytest.mark.asyncio
async def test_webhook_any_offer_handler_dry_run(tmp_path, monkeypatch):
    monkeypatch.setattr("amazon_mcp.integrations.sp_notifications._EVENT_LOG", tmp_path / "events.jsonl")
    payload = load_fixture("sp_api", "any_offer_changed_event.json")
    result = await handle_any_offer_changed_webhook(payload, dry_run=True)
    assert result["ok"] is True
    assert result["event"]["asin"] == "B0FIXTURE01"
    assert result["evaluation"]["feasibility"] == "viable_for_price_watches"
    assert (tmp_path / "events.jsonl").exists()


@pytest.mark.asyncio
async def test_inventory_event_rule_association_with_ctx():
    payload = load_fixture("sp_api", "fba_inventory_availability_changed_event.json")
    event = parse_notification_payload(payload)
    ctx = build_rule_context(
        ad_health={"status": "watch", "acos": 0.22, "score": 70},
        profit_snapshot={"net_margin_pct": 5.0, "total_revenue": 1000.0},
        account_health_check={"ok": True, "metrics": {"ipi_score": 450}},
        reorder_alerts=[{"asin": "B0FIXTURE01", "days_of_cover": 0.7}],
        replenishment_recommendations=[],
    )
    rule_eval = await reevaluate_cross_domain_rules_for_event(event, rule_ctx=ctx)
    hits = rule_eval["matched_rules"]
    assert any(h["rule_id"] == "pause_ads_low_cover" for h in hits)
    assert any("pause_ads_low_cover" in r for r in rule_eval["trigger_reasons"])


@pytest.mark.asyncio
async def test_inventory_webhook_full_chain_dry_run(tmp_path, monkeypatch, dry_sp):
    monkeypatch.setattr("amazon_mcp.integrations.sp_notifications._EVENT_LOG", tmp_path / "events.jsonl")
    store = AlertStore(str(tmp_path / "alerts.db"))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-FIX-001", "B0FIXTURE01", 20))
    payload = load_fixture("sp_api", "fba_inventory_availability_changed_event.json")
    ctx = build_rule_context(
        ad_health={"status": "watch", "acos": 0.22, "score": 70},
        profit_snapshot={"net_margin_pct": 5.0, "total_revenue": 1000.0},
        account_health_check={"ok": True, "metrics": {"ipi_score": 450}},
        reorder_alerts=[],
        replenishment_recommendations=[],
    )
    result = await handle_notification_webhook(
        payload,
        dry_run=True,
        sp=dry_sp,
        alert_store=store,
        rule_ctx=ctx,
        send_slack_snippet=True,
    )
    assert result["ok"] is True
    assert result["event"]["fulfillable_quantity"] == 8
    assert result["evaluation"]["feasibility"] == "viable_for_inventory_thresholds_and_reorder"
    assert result["slack_snippet"]
    assert "触发缘由" not in result["slack_snippet"]  # English template
    assert "FBA_INVENTORY_AVAILABILITY_CHANGES" in result["slack_snippet"]
    assert (tmp_path / "events.jsonl").exists()
    logged = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
    assert logged["event"]["asin"] == "B0FIXTURE01"


@pytest.mark.asyncio
async def test_build_event_slack_snippet_includes_decision_rationale():
    payload = load_fixture("sp_api", "fba_inventory_availability_changed_event.json")
    event = parse_notification_payload(payload)
    ctx = build_rule_context(
        ad_health={"status": "watch", "acos": 0.22, "score": 70},
        profit_snapshot={"net_margin_pct": 5.0, "total_revenue": 1000.0},
        account_health_check={"ok": True, "metrics": {"ipi_score": 450}},
        reorder_alerts=[{"asin": "B0FIXTURE01", "days_of_cover": 0.7}],
        replenishment_recommendations=[],
    )
    rule_eval = await reevaluate_cross_domain_rules_for_event(event, rule_ctx=ctx)
    snippet = build_event_slack_snippet(event, rule_eval)
    assert "Decision rationale" in snippet
    assert "pause_ads_low_cover" in snippet or "Pause or reduce ad spend" in snippet
