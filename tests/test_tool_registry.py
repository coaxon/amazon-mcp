"""Domain tool registry pilot — system + account."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from amazon_mcp.tools.registry import DOMAIN_HANDLERS, LEGACY_TOOL_ALIASES, dispatch_domain, dispatch_legacy, list_domain_actions


@pytest.fixture(autouse=True)
def _ensure_registry():
    import amazon_mcp.server  # noqa: F401
    yield


def test_domain_handlers_registered():
    assert "system" in DOMAIN_HANDLERS
    assert "account" in DOMAIN_HANDLERS
    assert set(list_domain_actions("system")) == {"auth_token", "health", "marketplaces", "metrics"}
    assert "feedback" in list_domain_actions("account")


def test_legacy_aliases_cover_pilot_tools():
    assert LEGACY_TOOL_ALIASES["amazon_health"] == ("system", "health")
    assert LEGACY_TOOL_ALIASES["get_seller_feedback"] == ("account", "feedback")


@pytest.mark.asyncio
async def test_dispatch_legacy_health_matches_envelope_data():
    legacy_raw = await dispatch_legacy("amazon_health")
    legacy = json.loads(legacy_raw)
    env_raw = await dispatch_domain("system", "health", "{}")
    env = json.loads(env_raw)
    assert legacy["ok"] is True
    assert env["ok"] is True
    assert env["domain"] == "amazon_system"
    assert env["action"] == "health"
    assert env["data"]["service"] == legacy["service"]
    assert env["data"]["tool_count"] == legacy["tool_count"]


@pytest.mark.asyncio
async def test_amazon_system_auth_token():
    raw = await dispatch_domain("system", "auth_token", "{}")
    data = json.loads(raw)
    assert data["ok"] is True
    assert "sp_api_token" in data["data"]


@pytest.mark.asyncio
async def test_amazon_account_feedback():
    raw = await dispatch_domain("account", "feedback", '{"days": 90}')
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["data"].get("ok") is True


@pytest.mark.asyncio
async def test_server_wrappers_via_handlers():
    from amazon_mcp.server import TOOL_HANDLERS
    assert "amazon_system" in TOOL_HANDLERS
    assert "amazon_account" in TOOL_HANDLERS
    health = json.loads(await TOOL_HANDLERS["amazon_health"]())
    via_system = json.loads(await TOOL_HANDLERS["amazon_system"]())
    health_service = health.get("service") or health.get("data", {}).get("service")
    assert health_service == via_system["data"]["service"]



def test_legacy_aliases_cover_migrated_batches_8domain():
    assert LEGACY_TOOL_ALIASES["product_lookup"] == ("catalog", "lookup")
    assert LEGACY_TOOL_ALIASES["get_fee_estimate"] == ("pricing", "fee_estimate")
    assert LEGACY_TOOL_ALIASES["list_orders"] == ("orders", "list")
    assert LEGACY_TOOL_ALIASES["inventory_levels"] == ("inventory", "levels")
    assert LEGACY_TOOL_ALIASES["create_sp_report"] == ("report", "create")
    assert LEGACY_TOOL_ALIASES["get_advertising_profile"] == ("ads", "profile")


@pytest.mark.asyncio
async def test_dispatch_legacy_product_lookup():
    raw = await dispatch_legacy("product_lookup", {"asin": "B0POC00001"})
    data = json.loads(raw)
    assert data.get("ok") is True
    assert data.get("asin") == "B0POC00001"


@pytest.mark.asyncio
async def test_amazon_catalog_envelope():
    raw = await dispatch_domain("catalog", "lookup", '{"asin": "B0POC00001"}')
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["domain"] == "amazon_catalog"
    assert env["action"] == "lookup"


@pytest.mark.asyncio
async def test_amazon_pricing_fee_estimate():
    raw = await dispatch_domain("pricing", "fee_estimate", '{"asin": "B0POC00001", "price": 29.99}')
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"].get("ok") is True

def test_all_domains_registered():
    expected = {
        "system", "account", "catalog", "pricing", "orders", "inventory", "listings", "report",
        "ads", "finance", "fulfillment", "analytics", "alerts", "insights", "notify", "billing",
        "features", "meli", "tiktok", "cross_platform",
        "rto_geo", "command_center", "benchmark", "admin", "inventory_pool", "sync_schedule",
    }
    assert expected == set(DOMAIN_HANDLERS.keys())


def test_legacy_aliases_batch3_domains():
    assert LEGACY_TOOL_ALIASES["get_financial_summary"] == ("finance", "financial_summary")
    assert LEGACY_TOOL_ALIASES["create_fba_inbound_plan"] == ("fulfillment", "create_inbound_plan")
    assert LEGACY_TOOL_ALIASES["get_sales_traffic_analytics"] == ("analytics", "sales_traffic")
    assert LEGACY_TOOL_ALIASES["configure_inventory_alert"] == ("alerts", "configure_inventory")
    assert LEGACY_TOOL_ALIASES["get_operations_health_report"] == ("insights", "operations_health")
    assert LEGACY_TOOL_ALIASES["get_notification_config"] == ("notify", "notification_config")


@pytest.mark.asyncio
async def test_amazon_finance_get_cogs_list():
    raw = await dispatch_domain("finance", "get_cogs", "{}")
    env = json.loads(raw)
    assert env["ok"] is True


@pytest.mark.asyncio
async def test_fba_reimbursement_summary_legacy():
    raw = await dispatch_legacy("get_fba_reimbursement_summary", {"days": 30})
    data = json.loads(raw)
    assert data.get("ok") is True
    assert data.get("reimbursement_count", 0) >= 0


@pytest.mark.asyncio
async def test_amazon_alerts_alert_config():
    raw = await dispatch_domain("alerts", "alert_config", "{}")
    env = json.loads(raw)
    assert env["ok"] is True



def test_billing_domain_registered():
    assert "billing" in DOMAIN_HANDLERS
    assert set(DOMAIN_HANDLERS["billing"].keys()) == {"usage_summary", "check_quota", "set_quota", "tier_limits", "month_usage"}
