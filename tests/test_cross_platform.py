"""Tests for cross-platform: Mercado Libre, TikTok Shop, and cross_platform domain."""
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


# ── PlatformSnapshot model ────────────────────────────────────────────────────

class TestPlatformSnapshot:
    def test_empty_snapshot(self):
        from amazon_mcp.connectors.platform_snapshot import PlatformSnapshot
        snap = PlatformSnapshot(platform="amazon", sites=["ATVPDKIKX0DER"])
        assert snap.total_units == 0
        assert snap.total_revenue_usd == 0.0
        assert snap.low_stock_skus == []

    def test_snapshot_with_orders(self):
        from amazon_mcp.connectors.platform_snapshot import PlatformSnapshot, OrderSummaryRow
        snap = PlatformSnapshot(
            platform="meli",
            sites=["MLA", "MLB"],
            orders=[
                OrderSummaryRow(site_id="MLA", units=10, revenue_usd=55.0, currency="ARS", period_days=7),
                OrderSummaryRow(site_id="MLB", units=5, revenue_usd=30.0, currency="BRL", period_days=7),
            ],
        )
        assert snap.total_units == 15
        assert snap.total_revenue_usd == 85.0

    def test_snapshot_low_stock(self):
        from amazon_mcp.connectors.platform_snapshot import PlatformSnapshot, InventoryRow
        snap = PlatformSnapshot(
            platform="meli",
            sites=["MLA"],
            inventory=[
                InventoryRow(sku="SKU-1", item_id="MLA1", title="T1", on_hand=2,
                             fulfillment_mode="FULL", site_id="MLA", low_stock=True),
                InventoryRow(sku="SKU-2", item_id="MLA2", title="T2", on_hand=50,
                             fulfillment_mode="FULL", site_id="MLA", low_stock=False),
            ],
        )
        assert "SKU-1" in snap.low_stock_skus
        assert "SKU-2" not in snap.low_stock_skus

    def test_to_briefing_dict_shape(self):
        from amazon_mcp.connectors.platform_snapshot import PlatformSnapshot
        snap = PlatformSnapshot(platform="tiktok", sites=["US-TTS"])
        d = snap.to_briefing_dict()
        assert d["platform"] == "tiktok"
        assert "orders" in d
        assert "inventory" in d


# ── Mercado Libre client ──────────────────────────────────────────────────────

class TestMeliApiClient:
    def test_dry_run_orders_summary_ok(self):
        from amazon_mcp.clients.meli_api import MeliApiClient
        client = MeliApiClient(site_ids=["MLA", "MLB"], dry_run=True)

        async def _run():
            return await client.get_orders_summary(days=7)

        result = asyncio.run(_run())
        assert result["ok"] is True
        assert result["platform"] == "meli"
        assert "total_units" in result
        assert "by_site" in result

    def test_dry_run_inventory_ok(self):
        from amazon_mcp.clients.meli_api import MeliApiClient
        client = MeliApiClient(site_ids=["MLA"], dry_run=True)

        async def _run():
            return await client.get_all_inventory()

        result = asyncio.run(_run())
        assert result["ok"] is True
        assert "items" in result

    def test_dry_run_account_health_ok(self):
        from amazon_mcp.clients.meli_api import MeliApiClient
        client = MeliApiClient(dry_run=True)

        async def _run():
            return await client.get_account_health()

        result = asyncio.run(_run())
        assert result["ok"] is True
        assert result["platform"] == "meli"

    def test_orders_have_by_site(self):
        from amazon_mcp.clients.meli_api import MeliApiClient
        client = MeliApiClient(site_ids=["MLA", "MLB"], dry_run=True)

        async def _run():
            return await client.get_orders_summary(days=7)

        result = asyncio.run(_run())
        site_ids = {s["site_id"] for s in result["by_site"]}
        assert "MLA" in site_ids

    def test_revenue_usd_is_float(self):
        from amazon_mcp.clients.meli_api import MeliApiClient
        client = MeliApiClient(site_ids=["MLA"], dry_run=True)

        async def _run():
            return await client.get_orders_summary(days=7)

        result = asyncio.run(_run())
        assert isinstance(result["total_revenue_usd"], float)


# ── TikTok client ─────────────────────────────────────────────────────────────

class TestTikTokApiClient:
    def test_dry_run_orders_ok(self):
        from amazon_mcp.clients.tiktok_api import TikTokApiClient
        client = TikTokApiClient(dry_run=True)

        async def _run():
            return await client.get_orders_summary(days=7)

        result = asyncio.run(_run())
        assert result["ok"] is True
        assert result["platform"] == "tiktok"
        assert "total_units" in result

    def test_dry_run_inventory_ok(self):
        from amazon_mcp.clients.tiktok_api import TikTokApiClient
        client = TikTokApiClient(dry_run=True)

        async def _run():
            return await client.get_inventory_summary()

        result = asyncio.run(_run())
        assert result["ok"] is True
        assert "items" in result

    def test_cancelled_orders_excluded(self):
        from amazon_mcp.clients.tiktok_api import TikTokApiClient
        client = TikTokApiClient(dry_run=True)

        async def _run():
            return await client.get_orders_summary(days=7)

        result = asyncio.run(_run())
        # fixture has 4 orders, 1 cancelled — active = 3
        assert result["total_orders"] == 3

    def test_by_sku_populated(self):
        from amazon_mcp.clients.tiktok_api import TikTokApiClient
        client = TikTokApiClient(dry_run=True)

        async def _run():
            return await client.get_orders_summary(days=7)

        result = asyncio.run(_run())
        assert len(result["by_sku"]) >= 1


# ── Meli domain via MCP tool ─────────────────────────────────────────────────

class TestMeliDomainTool:
    def test_orders_list_ok(self):
        amazon_meli = EXPORTS["amazon_meli"]
        raw = _call(amazon_meli("orders_list", days=7))
        assert raw["ok"] is True

    def test_orders_list_has_by_site(self):
        amazon_meli = EXPORTS["amazon_meli"]
        raw = _call(amazon_meli("orders_list", days=7))
        inner = _inner(raw)
        assert "by_site" in inner

    def test_inventory_get_ok(self):
        amazon_meli = EXPORTS["amazon_meli"]
        raw = _call(amazon_meli("inventory_get"))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert "items" in inner

    def test_account_health_ok(self):
        amazon_meli = EXPORTS["amazon_meli"]
        raw = _call(amazon_meli("account_health"))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert inner.get("platform") == "meli"

    def test_daily_snapshot_ok(self):
        amazon_meli = EXPORTS["amazon_meli"]
        raw = _call(amazon_meli("daily_snapshot", days=7))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert inner.get("platform") == "meli"

    def test_daily_snapshot_has_latam_alerts(self):
        amazon_meli = EXPORTS["amazon_meli"]
        raw = _call(amazon_meli("daily_snapshot"))
        inner = _inner(raw)
        assert "latam_alerts" in inner
        assert isinstance(inner["latam_alerts"], list)

    def test_daily_snapshot_has_inventory_and_orders(self):
        amazon_meli = EXPORTS["amazon_meli"]
        raw = _call(amazon_meli("daily_snapshot"))
        inner = _inner(raw)
        assert "orders" in inner
        assert "inventory" in inner

    def test_configure_site_shows_available_sites(self):
        amazon_meli = EXPORTS["amazon_meli"]
        raw = _call(amazon_meli("configure_site"))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert "available_sites" in inner or "current_site_ids" in inner


# ── TikTok domain via MCP tool ────────────────────────────────────────────────

class TestTikTokDomainTool:
    def test_orders_list_ok(self):
        amazon_tiktok = EXPORTS["amazon_tiktok"]
        raw = _call(amazon_tiktok("orders_list", days=7))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert inner.get("platform") == "tiktok"

    def test_inventory_get_ok(self):
        amazon_tiktok = EXPORTS["amazon_tiktok"]
        raw = _call(amazon_tiktok("inventory_get"))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert "items" in inner

    def test_daily_snapshot_ok(self):
        amazon_tiktok = EXPORTS["amazon_tiktok"]
        raw = _call(amazon_tiktok("daily_snapshot"))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert inner.get("platform") == "tiktok"

    def test_daily_snapshot_velocity_alerts(self):
        amazon_tiktok = EXPORTS["amazon_tiktok"]
        raw = _call(amazon_tiktok("daily_snapshot"))
        inner = _inner(raw)
        assert "velocity_alerts" in inner
        assert isinstance(inner["velocity_alerts"], list)

    def test_connection_status_ok(self):
        amazon_tiktok = EXPORTS["amazon_tiktok"]
        raw = _call(amazon_tiktok("connection_status"))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert inner.get("platform") == "tiktok"

    def test_phase_label_is_p1(self):
        amazon_tiktok = EXPORTS["amazon_tiktok"]
        raw = _call(amazon_tiktok("daily_snapshot"))
        inner = _inner(raw)
        assert "P1" in str(inner.get("phase", ""))


# ── Cross-platform domain ─────────────────────────────────────────────────────

class TestCrossPlatformDomainTool:
    def test_inventory_sync_ok(self):
        amazon_cross = EXPORTS["amazon_cross_platform"]
        raw = _call(amazon_cross("inventory_sync", days=7))
        inner = _inner(raw)
        assert inner.get("ok") is True

    def test_inventory_sync_has_revenue_summary(self):
        amazon_cross = EXPORTS["amazon_cross_platform"]
        raw = _call(amazon_cross("inventory_sync"))
        inner = _inner(raw)
        assert "revenue_summary" in inner
        assert "total_usd" in inner["revenue_summary"]

    def test_inventory_sync_has_platform_mix(self):
        amazon_cross = EXPORTS["amazon_cross_platform"]
        raw = _call(amazon_cross("inventory_sync"))
        inner = _inner(raw)
        mix = inner["revenue_summary"].get("platform_mix_pct", {})
        assert isinstance(mix, dict)

    def test_inventory_sync_has_cross_alerts(self):
        amazon_cross = EXPORTS["amazon_cross_platform"]
        raw = _call(amazon_cross("inventory_sync"))
        inner = _inner(raw)
        assert "cross_alerts" in inner
        assert isinstance(inner["cross_alerts"], list)

    def test_inventory_sync_platforms_active(self):
        amazon_cross = EXPORTS["amazon_cross_platform"]
        raw = _call(amazon_cross("inventory_sync", platforms="meli,tiktok"))
        inner = _inner(raw)
        assert "platforms_active" in inner

    def test_revenue_compare_ok(self):
        amazon_cross = EXPORTS["amazon_cross_platform"]
        raw = _call(amazon_cross("revenue_compare"))
        inner = _inner(raw)
        assert inner.get("ok") is True

    def test_latam_rules_check_ok(self):
        amazon_cross = EXPORTS["amazon_cross_platform"]
        raw = _call(amazon_cross("latam_rules_check"))
        inner = _inner(raw)
        assert inner.get("ok") is True
        assert "latam_alerts" in inner

    def test_latam_rules_evaluated(self):
        amazon_cross = EXPORTS["amazon_cross_platform"]
        raw = _call(amazon_cross("latam_rules_check"))
        inner = _inner(raw)
        rules = inner.get("rules_evaluated", [])
        assert "price_drift_vs_fx" in rules

    def test_connection_status_all_platforms(self):
        amazon_cross = EXPORTS["amazon_cross_platform"]
        raw = _call(amazon_cross("connection_status"))
        inner = _inner(raw)
        assert inner.get("ok") is True
        platforms = inner.get("platforms", {})
        assert "amazon" in platforms
        assert "meli" in platforms
        assert "tiktok" in platforms

    def test_connection_status_has_roadmap(self):
        amazon_cross = EXPORTS["amazon_cross_platform"]
        raw = _call(amazon_cross("connection_status"))
        inner = _inner(raw)
        roadmap = inner.get("roadmap", {})
        assert "P0" in roadmap
        assert any(k.startswith("P4") for k in roadmap)


# ── Domain registry ───────────────────────────────────────────────────────────

class TestCrossPlatformRegistry:
    def test_meli_domain_registered(self):
        from amazon_mcp.tools.registry import DOMAIN_HANDLERS
        assert "meli" in DOMAIN_HANDLERS
        assert set(DOMAIN_HANDLERS["meli"].keys()) == {
            "orders_list", "inventory_get", "account_health", "daily_snapshot", "configure_site"
        }

    def test_tiktok_domain_registered(self):
        from amazon_mcp.tools.registry import DOMAIN_HANDLERS
        assert "tiktok" in DOMAIN_HANDLERS
        assert set(DOMAIN_HANDLERS["tiktok"].keys()) == {
            "orders_list", "inventory_get", "daily_snapshot", "connection_status"
        }

    def test_cross_platform_domain_registered(self):
        from amazon_mcp.tools.registry import DOMAIN_HANDLERS
        assert "cross_platform" in DOMAIN_HANDLERS
        assert "inventory_sync" in DOMAIN_HANDLERS["cross_platform"]
        assert "connection_status" in DOMAIN_HANDLERS["cross_platform"]
