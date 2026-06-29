"""Tests for dom_refiner compression and LWA TokenState."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from amazon_mcp.auth.lwa import LWAAuth, TokenState
from amazon_mcp.refiner.dom_refiner import (
    refine_ads,
    refine_competitive,
    refine_inventory,
    refine_order_summary,
    refine_pricing,
    refine_product,
    refine_search_results,
)


def test_refine_product_strips_noise():
    raw = {
        "ok": True,
        "asin": "B0TEST",
        "title": "Widget",
        "brand": "Acme",
        "rank": 42,
        "dimensions": {"length": 99},
        "raw_payload": {"huge": "nested" * 100},
    }
    out = refine_product(raw)
    assert set(out.keys()) <= {
        "ok", "asin", "title", "brand", "price", "buybox_winner",
        "buybox_pct", "sales_rank", "review_count", "rating",
    }
    assert out["asin"] == "B0TEST"
    assert out["sales_rank"] == 42
    assert "dimensions" not in out


def test_refine_inventory_core_fields():
    raw = {
        "ok": True,
        "summaries": [{
            "sku": "SKU-1",
            "asin": "B0INV",
            "fulfillableQuantity": 100,
            "inboundWorkingQuantity": 5,
            "inboundShippedQuantity": 3,
            "reservedQuantity": {"totalReservedQuantity": 99},
        }],
    }
    out = refine_inventory(raw)
    assert out["count"] == 1
    item = out["items"][0]
    assert item["sku"] == "SKU-1"
    assert item["fulfillable_qty"] == 100
    assert item["inbound_qty"] == 8
    assert "reservedQuantity" not in item


def test_refine_inventory_days_remaining():
    raw = {
        "ok": True,
        "summaries": [{"sku": "S", "asin": "A", "fulfillableQuantity": 30, "daily_rate": 10}],
    }
    assert refine_inventory(raw)["items"][0]["inventory_days_remaining"] == 3.0


def test_refine_pricing_compact():
    raw = {
        "ok": True,
        "prices": [{
            "asin": "B0P",
            "your_price": 29.99,
            "lowest_new": 27.0,
            "buy_box_price": 28.5,
            "offer_count": 4,
        }],
    }
    out = refine_pricing(raw)
    p = out["prices"][0]
    assert p["our_price"] == 29.99
    assert p["competitor_count"] == 4
    assert "status" not in p


def test_refine_ads_keyword_top10():
    raw = {
        "ok": True,
        "campaign_name": "Camp-A",
        "spend": 100.0,
        "sales": 500.0,
        "acos": 20.0,
        "roas": 5.0,
        "impressions": 1000,
        "clicks": 50,
        "ctr": 0.05,
        "keyword_top10": [{"keyword": "widget", "spend": 10, "sales": 50, "acos": 20}],
    }
    out = refine_ads(raw)
    assert out["campaign_name"] == "Camp-A"
    assert len(out["keyword_top10"]) == 1


def test_refine_order_summary_aggregates():
    raw = {"ok": True, "orders_count": 2, "total_revenue": 100.0, "top_asin": "B0TOP"}
    out = refine_order_summary(raw)
    assert out["orders_count"] == 2
    assert out["avg_order_value"] == 50.0


def test_refine_competitive_price_gap():
    raw = {"ok": True, "asin": "B0C", "our_price": 100.0, "lowest_new": 90.0, "competitor_count": 3}
    out = refine_competitive(raw)
    assert out["price_gap_pct"] == 10.0


def test_refine_search_results_list():
    raw = {"ok": True, "keywords": "widget", "items": [{"asin": "B1", "title": "A", "brand": "X", "rank": 1}]}
    out = refine_search_results(raw)
    assert out["count"] == 1


def test_token_state_fresh_expiring_expired():
    auth = LWAAuth("id", "secret", "refresh", shared_cache=False)
    auth._access_token = "tok"
    auth._expires_at = time.time() + 600
    assert auth.token_state == TokenState.FRESH
    auth._expires_at = time.time() + 120
    assert auth.token_state == TokenState.EXPIRING
    auth._expires_at = time.time() - 1
    assert auth.token_state == TokenState.EXPIRED


@pytest.mark.asyncio
async def test_ensure_fresh_returns_cached_token_when_fresh():
    auth = LWAAuth("id", "secret", "refresh", shared_cache=False)
    auth._access_token = "cached-token"
    auth._expires_at = time.time() + 3600
    assert await auth.ensure_fresh() == "cached-token"
    assert auth.token_state == TokenState.FRESH
