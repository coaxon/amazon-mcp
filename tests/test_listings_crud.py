"""Tests for Listings CRUD domain — preview/confirm pattern."""
from __future__ import annotations

import asyncio
import json
import os
import pytest

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")

import amazon_mcp.server as _srv
from amazon_mcp.tools.domain_tools import EXPORTS


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    _srv._reset_ctx_cache()


def _call(coro):
    return json.loads(asyncio.run(coro))


def _inner(raw: dict) -> dict:
    return raw.get("data", raw)


class TestGetListing:
    def test_returns_ok(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("get_listing", sku="SKU-001"))
        assert raw["ok"] is True

    def test_missing_sku_returns_error(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("get_listing"))
        inner = _inner(raw)
        assert inner.get("ok") is False
        assert "error" in inner

    def test_returns_sku_field(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("get_listing", sku="SKU-TEST-001"))
        inner = _inner(raw)
        assert inner.get("sku") == "SKU-TEST-001"

    def test_has_status(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("get_listing", sku="SKU-001"))
        inner = _inner(raw)
        assert "status" in inner

    def test_has_offers(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("get_listing", sku="SKU-001"))
        inner = _inner(raw)
        assert "offers" in inner


class TestUpdatePrice:
    def test_preview_without_confirm(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("update_price", sku="SKU-001", price=29.99))
        inner = _inner(raw)
        assert inner.get("preview_only") is True
        assert inner.get("action") == "update_price"

    def test_preview_has_proposed(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("update_price", sku="SKU-001", price=24.99))
        inner = _inner(raw)
        proposed = inner.get("proposed") or {}
        assert proposed.get("price") == 24.99
        assert proposed.get("sku") == "SKU-001"

    def test_preview_has_instructions(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("update_price", sku="SKU-001", price=19.99))
        inner = _inner(raw)
        assert "confirm=True" in str(inner.get("instructions", ""))

    def test_confirm_applies_change(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("update_price", sku="SKU-001", price=29.99, confirm=True))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert inner.get("action") == "update_price"
        assert inner.get("preview_only") is not True

    def test_confirm_dry_run_returns_accepted(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("update_price", sku="SKU-001", price=29.99, confirm=True))
        inner = _inner(raw)
        assert inner.get("status") == "ACCEPTED"

    def test_missing_sku_returns_error(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("update_price", price=29.99))
        inner = _inner(raw)
        assert inner.get("ok") is False

    def test_zero_price_returns_error(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("update_price", sku="SKU-001", price=0.0))
        inner = _inner(raw)
        assert inner.get("ok") is False


class TestUpdateQuantity:
    def test_preview_without_confirm(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("update_quantity", sku="SKU-001", quantity=100))
        inner = _inner(raw)
        assert inner.get("preview_only") is True

    def test_confirm_applies_change(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("update_quantity", sku="SKU-001", quantity=50, confirm=True))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert inner.get("preview_only") is not True

    def test_zero_quantity_allowed(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("update_quantity", sku="SKU-001", quantity=0, confirm=True))
        inner = _inner(raw)
        assert inner.get("ok") is True


class TestDeactivateAndActivateListing:
    def test_deactivate_preview(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("deactivate_listing", sku="SKU-001"))
        inner = _inner(raw)
        assert inner.get("preview_only") is True
        proposed = inner.get("proposed") or {}
        assert proposed.get("status") == "INACTIVE"

    def test_activate_preview(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("activate_listing", sku="SKU-001"))
        inner = _inner(raw)
        assert inner.get("preview_only") is True
        proposed = inner.get("proposed") or {}
        assert proposed.get("status") == "ACTIVE"

    def test_deactivate_confirm_returns_accepted(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("deactivate_listing", sku="SKU-001", confirm=True))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert inner.get("status") == "ACCEPTED"

    def test_activate_confirm_returns_accepted(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("activate_listing", sku="SKU-001", confirm=True))
        inner = _inner(raw)
        assert inner.get("ok") is True


class TestDeleteListing:
    def test_preview_warns_irreversibility(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("delete_listing", sku="SKU-OLD-001"))
        inner = _inner(raw)
        assert inner.get("preview_only") is True
        proposed = inner.get("proposed") or {}
        assert "PERMANENT" in str(proposed.get("effect", "")).upper()

    def test_preview_has_warning(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("delete_listing", sku="SKU-OLD-001"))
        inner = _inner(raw)
        proposed = inner.get("proposed") or {}
        assert "deactivate_listing" in str(proposed.get("warning", ""))

    def test_confirm_deletes_in_dry_run(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("delete_listing", sku="SKU-OLD-001", confirm=True))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert inner.get("status") == "DELETED"

    def test_missing_sku_returns_error(self):
        amazon_listings = EXPORTS["amazon_listings"]
        raw = _call(amazon_listings("delete_listing"))
        inner = _inner(raw)
        assert inner.get("ok") is False
