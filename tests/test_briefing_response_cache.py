"""Briefing-path response cache TTL behaviour."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from amazon_mcp.auth.lwa import LWAAuth
from amazon_mcp.clients.rate_limit import RateLimitRegistry
from amazon_mcp.clients.response_cache import ResponseCache, CACHE_MISS, BRIEFING_CACHE_TTL, briefing_cache_ttl
from amazon_mcp.clients.sp_api import SPAPIClient
from amazon_mcp.config import AmazonConfig


def test_briefing_cache_ttl_constants():
    assert briefing_cache_ttl("inventory") == 600
    assert briefing_cache_ttl("sales_by_asin") == 3600
    assert briefing_cache_ttl("unknown") == BRIEFING_CACHE_TTL["default"]


def test_response_cache_per_key_ttl_override():
    cache = ResponseCache(ttl_seconds=300)
    cache.set("short", "a", ttl_seconds=1)
    cache.set("long", "b", ttl_seconds=3600)
    assert cache.get("short") == "a"
    expires_at, value = cache._store["short"]
    cache._store["short"] = (time.monotonic() - 1, value)
    assert cache.get("short") is CACHE_MISS
    assert cache.get("long") == "b"


@pytest.mark.asyncio
async def test_get_sales_by_asin_cache_hit_dry_run():
    cfg = AmazonConfig(
        lwa_client_id="x", lwa_client_secret="x", lwa_refresh_token="x",
        sp_region="na", marketplace_id="ATVPDKIKX0DER", seller_id="seller-a",
        ads_client_id="", ads_client_secret="", ads_refresh_token="", ads_profile_id="",
        dry_run=True, cache_ttl_seconds=300,
    )
    sp = SPAPIClient(cfg, LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token), RateLimitRegistry())
    calls = {"n": 0}
    orig = sp._cache.set

    def _counting_set(key, value, *, ttl_seconds=None):
        calls["n"] += 1
        return orig(key, value, ttl_seconds=ttl_seconds)

    with patch.object(sp._cache, "set", side_effect=_counting_set):
        r1 = await sp.get_sales_by_asin(30)
        r2 = await sp.get_sales_by_asin(30)
    assert r1 == r2
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_inventory_summaries_uses_inventory_ttl():
    cfg = AmazonConfig(
        lwa_client_id="x", lwa_client_secret="x", lwa_refresh_token="x",
        sp_region="na", marketplace_id="ATVPDKIKX0DER", seller_id="seller-a",
        ads_client_id="", ads_client_secret="", ads_refresh_token="", ads_profile_id="",
        dry_run=True, cache_ttl_seconds=300,
    )
    sp = SPAPIClient(cfg, LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token), RateLimitRegistry())
    captured: dict = {}

    def _capture_set(key, value, *, ttl_seconds=None):
        captured["ttl"] = ttl_seconds
        return ResponseCache.set(sp._cache, key, value, ttl_seconds=ttl_seconds)

    with patch.object(sp._cache, "set", side_effect=_capture_set):
        await sp.get_inventory_summaries()
    assert captured.get("ttl") == briefing_cache_ttl("inventory")
