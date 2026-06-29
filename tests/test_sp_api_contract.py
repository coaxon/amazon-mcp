"""Contract tests: official-format fixtures → parser functions (black-box)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from fixtures.fixture_sp_client import FixtureSPClient
from fixtures.loader import load_fixture
from amazon_mcp.clients.sp_api import (
    _parse_catalog_item_data,
    _parse_competitive_pricing_data,
    parse_fees_estimate_response,
    parse_financial_events_response,
    parse_product_pricing_response,
)


@pytest.mark.asyncio
async def test_product_pricing_fixture_parses():
    result = parse_product_pricing_response(load_fixture("sp_api", "product_pricing.json"))
    assert result["ok"] is True
    assert result["count"] == 2
    assert result["prices"][0]["asin"] == "B0FIXTURE01"
    assert result["prices"][0]["buy_box_price"] == 29.99


@pytest.mark.asyncio
async def test_competitive_pricing_fixture_parses():
    result = _parse_competitive_pricing_data(load_fixture("sp_api", "competitive_pricing_offers.json"), "B0FIXTURE01")
    assert result["buy_box_price"] == 28.99
    assert result["offer_count"] == 3
    assert result["offers"][0]["prime"] is True


@pytest.mark.asyncio
async def test_inventory_summaries_fixture_parses():
    client = FixtureSPClient()
    result = await client.get_inventory_summaries(["SKU-FIX-001"])
    assert result["count"] >= 1
    assert "SKU-FIX-001" in result["low_stock_alerts"]


@pytest.mark.asyncio
async def test_financial_events_fixture_parses():
    result = parse_financial_events_response(load_fixture("sp_api", "financial_events.json"), 30)
    assert result["gross_revenue"] == 4480.0
    assert result["refunds"] == 155.0
    assert result["fee_breakdown"]["referral"] == 672.0
    assert result["fee_breakdown"]["fba"] == 235.0


@pytest.mark.asyncio
async def test_catalog_item_fixture_parses():
    result = _parse_catalog_item_data(load_fixture("sp_api", "catalog_item.json"), "B0FIXTURE01", "ATVPDKIKX0DER")
    assert result["title"] == "Fixture Wireless Bluetooth Speaker"
    assert result["brand"] == "FixtureBrand"
    assert result["category_browse_path"][0]["displayName"] == "Electronics"


@pytest.mark.asyncio
async def test_fees_estimate_fixture_parses():
    result = parse_fees_estimate_response(load_fixture("sp_api", "fees_estimate.json"), "B0FIXTURE01", 29.99)
    assert result["total_fees"] == 8.50
    assert result["net_revenue"] == pytest.approx(21.49)


@pytest.mark.asyncio
async def test_get_product_pricing_empty_list():
    """Empty ASIN list must return ok=True with empty prices, not send to API."""
    from amazon_mcp.clients.sp_api import SPAPIClient
    from amazon_mcp.config import AmazonConfig
    from amazon_mcp.auth.lwa import LWAAuth
    from amazon_mcp.clients.rate_limit import RateLimitRegistry
    cfg = AmazonConfig(
        lwa_client_id="x", lwa_client_secret="x", lwa_refresh_token="x",
        sp_region="na", marketplace_id="ATVPDKIKX0DER", seller_id="x",
        ads_client_id="", ads_client_secret="", ads_refresh_token="", ads_profile_id="",
        dry_run=False, cache_ttl_seconds=0,
    )
    sp = SPAPIClient(cfg, LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token), RateLimitRegistry())
    result = await sp.get_product_pricing([])
    assert result["ok"] is True
    assert result["prices"] == []


@pytest.mark.asyncio
async def test_response_cache_hit():
    # Verify ResponseCache TTL, size, and hit behaviour
    from amazon_mcp.clients.sp_api import SPAPIClient
    from amazon_mcp.config import AmazonConfig
    from amazon_mcp.auth.lwa import LWAAuth
    from amazon_mcp.clients.rate_limit import RateLimitRegistry
    cfg = AmazonConfig(
        lwa_client_id="x", lwa_client_secret="x", lwa_refresh_token="x",
        sp_region="na", marketplace_id="ATVPDKIKX0DER", seller_id="x",
        ads_client_id="", ads_client_secret="", ads_refresh_token="", ads_profile_id="",
        dry_run=True, cache_ttl_seconds=300,
    )
    sp = SPAPIClient(cfg, LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token), RateLimitRegistry())
    # dry_run skips cache but we can verify cache_ttl_seconds=0 disables caching
    assert sp._cache.ttl == 300

    # Verify ResponseCache basics
    from amazon_mcp.clients.response_cache import ResponseCache, CACHE_MISS
    cache = ResponseCache(ttl_seconds=60)
    assert cache.get("key") is CACHE_MISS
    cache.set("key", {"ok": True})
    assert cache.get("key") == {"ok": True}
    assert cache.size == 1
    cache.invalidate()
    assert cache.size == 0


def test_response_cache_ttl_zero_disables():
    # TTL=0 must never cache entries
    from amazon_mcp.clients.response_cache import ResponseCache, CACHE_MISS
    cache = ResponseCache(ttl_seconds=0)
    cache.set("k", "v")
    assert cache.size == 0
    assert cache.get("k") is CACHE_MISS


def test_response_cache_expiry():
    """Entries past TTL must be evicted on read."""
    import time
    from amazon_mcp.clients.response_cache import ResponseCache, CACHE_MISS
    cache = ResponseCache(ttl_seconds=1)
    cache.set("k", "v")
    assert cache.get("k") == "v"
    # Manually backdating the entry to simulate expiry
    key = "k"
    expires_at, value = cache._store[key]
    cache._store[key] = (time.monotonic() - 1, value)  # force expire
    assert cache.get(key) is CACHE_MISS
    assert cache.size == 0  # evicted on read


def test_response_cache_prefix_invalidate():
    """invalidate(prefix) must remove matching keys only."""
    from amazon_mcp.clients.response_cache import ResponseCache, CACHE_MISS
    cache = ResponseCache(ttl_seconds=60)
    cache.set("catalog:B001", 1)
    cache.set("catalog:B002", 2)
    cache.set("comp_pricing:B001", 3)
    cache.invalidate("catalog:")
    assert cache.get("catalog:B001") is CACHE_MISS
    assert cache.get("catalog:B002") is CACHE_MISS
    assert cache.get("comp_pricing:B001") == 3


@pytest.mark.asyncio
async def test_inventory_summaries_cache_hit_dry_run():
    """Second dry_run call should hit in-process cache (black-box, no private mocks)."""
    from amazon_mcp.clients.sp_api import SPAPIClient
    from amazon_mcp.config import AmazonConfig
    from amazon_mcp.auth.lwa import LWAAuth
    from amazon_mcp.clients.rate_limit import RateLimitRegistry

    cfg = AmazonConfig(
        lwa_client_id="x", lwa_client_secret="x", lwa_refresh_token="x",
        sp_region="na", marketplace_id="ATVPDKIKX0DER", seller_id="seller-cache",
        ads_client_id="", ads_client_secret="", ads_refresh_token="", ads_profile_id="",
        dry_run=True, cache_ttl_seconds=300,
    )
    sp = SPAPIClient(cfg, LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token), RateLimitRegistry())
    assert sp._cache.size == 0
    r1 = await sp.get_inventory_summaries(None)
    r2 = await sp.get_inventory_summaries(None)
    assert r1 == r2
    assert r1.get("dry_run") is True
    assert sp._cache.size >= 1
