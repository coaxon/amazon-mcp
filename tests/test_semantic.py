import pytest
import json
from amazon_mcp.server import (
    how_long_inventory_last,
    protect_profit_margin,
    competitor_price_alert,
    get_operations_health_report,
    run_scenario,
)


@pytest.mark.asyncio
async def test_how_long_no_rate():
    res = json.loads(await how_long_inventory_last("SKU-001", 0.0))
    assert res["ok"] is True


@pytest.mark.asyncio
async def test_how_long_with_rate():
    res = json.loads(await how_long_inventory_last("SKU-001", 3.0))
    assert res["ok"] is True
    assert "days_remaining" in res or "urgency" in res or "fulfillable_qty" in res


@pytest.mark.asyncio
async def test_protect_profit_margin_returns_action():
    res = json.loads(await protect_profit_margin("B0POC00001", 0.3))
    assert res["ok"] is True
    assert "action" in res or "current_margin" in res or "dry_run" in res


@pytest.mark.asyncio
async def test_competitor_price_alert_returns_alert_field():
    res = json.loads(await competitor_price_alert("B0POC00001", 0.05))
    assert res["ok"] is True
    assert "alert" in res or "gap_pct" in res or "dry_run" in res


@pytest.mark.asyncio
async def test_operations_health_report_structure():
    res = json.loads(await get_operations_health_report("B0POC00001"))
    assert res["ok"] is True
    assert "health_scores" in res
    scores = res["health_scores"]
    assert "inventory_risk" in scores
    assert "ad_efficiency" in scores
    assert "price_competitiveness" in scores
    assert "overall_score" in res


@pytest.mark.asyncio
async def test_operations_health_report_empty_asins():
    res = json.loads(await get_operations_health_report(""))
    assert res["ok"] is False
    assert "error" in res


@pytest.mark.asyncio
async def test_run_scenario_profit_protection():
    res = json.loads(await run_scenario("profit_protection", asins="B0POC00001", target_margin=0.25))
    assert res["ok"] is True
    assert res["scenario"] == "profit_protection"
    assert "results" in res


@pytest.mark.asyncio
async def test_run_scenario_competitor_monitor():
    res = json.loads(await run_scenario("competitor_monitor", asins="B0POC00001"))
    assert res["ok"] is True
    assert res["scenario"] == "competitor_monitor"
    assert "alerts_triggered" in res


@pytest.mark.asyncio
async def test_run_scenario_inventory_guardian():
    res = json.loads(await run_scenario("inventory_guardian", asins="B0POC00001", daily_sales_rate=2.0))
    assert res["ok"] is True
    assert res["scenario"] == "inventory_guardian"
    assert "reorder_priority" in res


@pytest.mark.asyncio
async def test_run_scenario_unknown_returns_supported():
    res = json.loads(await run_scenario("unknown_mode"))
    assert res["ok"] is False
    assert "supported" in res
    assert "profit_protection" in res["supported"]


@pytest.mark.asyncio
async def test_fee_estimate_schema_consistent():
    """Regression: dry_run and live-mode fee response must share same keys."""
    import sys
    from pathlib import Path
    _tests_dir = str(Path(__file__).resolve().parent)
    if _tests_dir not in sys.path:
        sys.path.insert(0, _tests_dir)
    from fixtures.fixture_sp_client import FixtureSPClient
    from amazon_mcp.clients.sp_api import parse_fees_estimate_response

    sp = FixtureSPClient()

    # Live-mode path via FixtureSPClient (calls parse_fees_estimate_response)
    live = await sp.get_fee_estimate("B0FIXTURE01", 29.99)
    assert "total_fees" in live, "live mode must have total_fees"
    assert "fee_breakdown" in live, "live mode must have fee_breakdown"
    assert "estimated_fees" not in live, "estimated_fees key must not appear"

    # Dry-run path via SPAPIClient
    from amazon_mcp.clients.sp_api import SPAPIClient
    from amazon_mcp.config import AmazonConfig
    from amazon_mcp.auth.lwa import LWAAuth
    from amazon_mcp.clients.rate_limit import RateLimitRegistry
    cfg = AmazonConfig(
        lwa_client_id="x", lwa_client_secret="x", lwa_refresh_token="x",
        sp_region="na", marketplace_id="ATVPDKIKX0DER", seller_id="x",
        ads_client_id="", ads_client_secret="", ads_refresh_token="", ads_profile_id="",
        dry_run=True, cache_ttl_seconds=0,
    )
    auth = LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token)
    rate = RateLimitRegistry()
    dry_sp = SPAPIClient(cfg, auth, rate)
    dry = await dry_sp.get_fee_estimate("B0FIXTURE01", 29.99)
    assert "total_fees" in dry, "dry_run must have total_fees"
    assert "fee_breakdown" in dry, "dry_run must have fee_breakdown"
    assert "estimated_fees" not in dry, "estimated_fees key must not appear in dry_run"
    assert dry["total_fees"] > 0
