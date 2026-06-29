"""Black-box SP client that returns live-parsed outputs from official fixtures."""
from __future__ import annotations

from amazon_mcp.clients.sp_api import (
    _fulfillable_quantity,
    _parse_catalog_item_data,
    _parse_competitive_pricing_data,
    parse_financial_events_response,
    parse_fees_estimate_response,
    parse_product_pricing_response,
)
from .loader import load_fixture


class FixtureSPClient:
    """Test double implementing public SP-API methods without private HTTP mocks."""

    marketplace_id = "ATVPDKIKX0DER"

    async def get_inventory_summaries(self, skus: list[str] | None = None) -> dict:
        data = load_fixture("sp_api", "inventory_summaries.json")
        summaries = data.get("payload", {}).get("inventorySummaries", [])
        if skus:
            sku_set = set(skus)
            summaries = [s for s in summaries if s.get("sellerSku") in sku_set]
        alerts = [s.get("sellerSku") for s in summaries if _fulfillable_quantity(s) < 10]
        return {"ok": True, "count": len(summaries), "summaries": summaries, "low_stock_alerts": alerts}

    async def get_competitive_pricing(self, asin: str) -> dict:
        data = load_fixture("sp_api", "competitive_pricing_offers.json")
        return _parse_competitive_pricing_data(data, asin)

    async def get_catalog_item(self, asin: str) -> dict:
        data = load_fixture("sp_api", "catalog_item.json")
        return _parse_catalog_item_data(data, asin, self.marketplace_id)

    async def get_product_pricing(self, asins: list[str]) -> dict:
        return parse_product_pricing_response(load_fixture("sp_api", "product_pricing.json"))

    async def get_financial_events(self, days: int = 30) -> dict:
        return parse_financial_events_response(load_fixture("sp_api", "financial_events.json"), days)

    async def get_fee_estimate(self, asin: str, price: float) -> dict:
        return parse_fees_estimate_response(load_fixture("sp_api", "fees_estimate.json"), asin, price)

    async def get_sales_by_asin(self, days: int = 30) -> dict:
        data = load_fixture("sp_api", "sales_by_asin.json")
        key = "7" if days <= 7 else "30"
        asins = data.get(key) or data.get("30") or []
        return {"ok": True, "dry_run": True, "period_days": days, "asins": asins}

    async def create_inbound_plan(self, items, address, plan_name: str = "") -> dict:
        return {
            "ok": True,
            "dry_run": True,
            "inboundPlanId": "FBA-PLAN-DRY-001",
            "operationId": "OP-DRY-001",
            "destinationFc": "LAX9",
            "status": "CREATED",
        }

