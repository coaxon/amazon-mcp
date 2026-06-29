"""Profit snapshot scenario tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.scenarios.profit_snapshot import build_profit_snapshot
from fixtures.fixture_sp_client import FixtureSPClient
from amazon_mcp.clients.ads_api import AdsAPIClient
from amazon_mcp.config import AmazonConfig
from amazon_mcp.auth.lwa import LWAAuth
from amazon_mcp.clients.rate_limit import RateLimitRegistry


@pytest.fixture
def dry_clients(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    cfg = AmazonConfig.from_env()
    auth = LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token)
    limits = RateLimitRegistry()
    sp = FixtureSPClient()
    ads = AdsAPIClient(cfg, auth, limits)
    return sp, ads


@pytest.mark.asyncio
async def test_profit_snapshot_fixture_fee_breakdown(dry_clients):
    sp, ads = dry_clients
    snap = await build_profit_snapshot(sp, ads, days=30, dry_run=True)

    assert snap["period"] == "last 30 days"
    assert snap["total_revenue"] == 4480.0
    bd = snap["total_fees_breakdown"]
    assert bd["referral"] == 672.0
    assert bd["fba"] == 235.0
    assert bd["refunds"] == 155.0
    assert bd["ads"] == 1020.0
    assert bd["ads"] / snap["total_revenue"] <= 0.40
    assert snap["data_completeness"]["fee_breakdown_available"] is True
    assert snap["data_completeness"]["ad_spend_source"] == "get_product_ad_performance"


@pytest.mark.asyncio
async def test_profit_snapshot_realistic_margins(dry_clients):
    sp, ads = dry_clients
    snap = await build_profit_snapshot(sp, ads, days=30, target_margin_pct=15.0, dry_run=True)

    assert -20 <= snap["net_margin_pct"] <= 25
    b1 = snap["by_asin"]["B0FIXTURE01"]
    b2 = snap["by_asin"]["B0FIXTURE02"]
    assert 12 <= b1["net_margin_pct"] <= 18
    assert -15 <= b2["net_margin_pct"] <= -5
    assert b1["revenue"] == 3240.0
    assert b2["revenue"] == 1240.0
    assert b2["ad_spend"] / b2["revenue"] <= 0.40


@pytest.mark.asyncio
async def test_profit_snapshot_asins_below_target(dry_clients):
    sp, ads = dry_clients
    snap = await build_profit_snapshot(sp, ads, days=30, target_margin_pct=15.0, dry_run=True)
    below = snap["asins_below_target_margin"]
    asins = {row["asin"] for row in below}
    assert "B0FIXTURE02" in asins
    assert "B0FIXTURE01" not in asins
    b2 = next(r for r in below if r["asin"] == "B0FIXTURE02")
    assert b2["net_margin_pct"] == pytest.approx(-8.2, abs=0.2)


@pytest.mark.asyncio
async def test_profit_snapshot_with_explicit_cogs(dry_clients):
    sp, ads = dry_clients
    params = {"cogs_by_asin": {"B0FIXTURE01": 1500.0, "B0FIXTURE02": 460.0}}
    snap = await build_profit_snapshot(sp, ads, days=30, params=params)
    assert snap["data_completeness"]["cogs_provided"] is True
    assert snap["by_asin"]["B0FIXTURE01"]["cogs"] == 1500.0
