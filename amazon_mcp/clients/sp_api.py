from __future__ import annotations

import asyncio
import gzip
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from amazon_mcp.auth.lwa import LWAAuth
from amazon_mcp.clients.http_retry import raise_on_429
from amazon_mcp.clients.rate_limit import RateLimitRegistry
from amazon_mcp.clients.response_cache import ResponseCache, CACHE_MISS, briefing_cache_ttl
from amazon_mcp.config import AmazonConfig

_SP_ENDPOINTS = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}

_REPORT_TYPES = {
    "sales_traffic": "GET_SALES_AND_TRAFFIC_REPORT",
    "inventory": "GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA",
    "listings": "GET_MERCHANT_LISTINGS_ALL_DATA",
    "orders": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
    "settlement": "GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2",
    "returns": "GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA",
    "fees": "GET_FBA_ESTIMATED_FBA_FEES_TXT_DATA",
    "reimbursements": "GET_FBA_REIMBURSEMENTS_DATA",
    "account_health": "GET_V2_SELLER_PERFORMANCE_REPORT",
    "inventory_planning": "GET_FBA_INVENTORY_PLANNING_DATA",
    "storage_fees": "GET_FBA_STORAGE_FEE_CHARGES_DATA",
    "restock_recommendations": "GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT",
}




from pathlib import Path as _Path
import json as _json

_FIXTURES_DIR = _Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"


def _load_fixture(*parts: str) -> dict[str, Any]:
    path = _FIXTURES_DIR.joinpath(*parts)
    with path.open(encoding="utf-8") as f:
        return _json.load(f)


def _classification_path(node: dict[str, Any] | None) -> list[dict[str, str]]:
    """Walk parent chain from leaf classification to root (Browse Tree path)."""
    path: list[dict[str, str]] = []
    cur = node
    while cur:
        path.append({
            "displayName": str(cur.get("displayName") or ""),
            "classificationId": str(cur.get("classificationId") or ""),
        })
        cur = cur.get("parent")
    return list(reversed(path))


def _parse_catalog_item_data(data: dict[str, Any], asin: str, marketplace_id: str) -> dict[str, Any]:
    summaries = data.get("summaries", [{}])
    s = summaries[0] if summaries else {}
    sales_ranks = data.get("salesRanks", [{}])
    rank = None
    category = None
    if sales_ranks:
        ranks = sales_ranks[0].get("ranks", [])
        if ranks:
            rank = ranks[0].get("rank")
            category = ranks[0].get("title")

    browse_classification = s.get("browseClassification") or {}
    classifications_block = (data.get("classifications") or [{}])[0]
    class_nodes = classifications_block.get("classifications") or []
    leaf = class_nodes[0] if class_nodes else None
    category_path = _classification_path(leaf) if leaf else _classification_path(browse_classification) if browse_classification else []

    return {
        "ok": True,
        "asin": asin,
        "title": s.get("itemName"),
        "brand": s.get("brand") or s.get("brandName"),
        "color": s.get("color") or s.get("colorName"),
        "size": s.get("size") or s.get("sizeName"),
        "marketplace_id": marketplace_id,
        "rank": rank,
        "category": category or (category_path[-1]["displayName"] if category_path else None),
        "browse_classification": browse_classification,
        "category_browse_path": category_path,
        "leaf_classification_id": category_path[-1]["classificationId"] if category_path else browse_classification.get("classificationId"),
        "raw": data,
    }


def _parse_competitive_pricing_data(data: dict[str, Any], asin: str) -> dict[str, Any]:
    payload = data.get("payload", {})
    summary = payload.get("Summary", {})
    offers = payload.get("Offers", [])
    result_offers = []
    for o in offers[:20]:
        listing = o.get("ListingPrice", {})
        shipping = o.get("Shipping", {})
        result_offers.append({
            "seller": o.get("SellerId"),
            "price": listing.get("Amount"),
            "currency": listing.get("CurrencyCode", "USD"),
            "shipping": shipping.get("Amount", 0),
            "condition": o.get("SubCondition"),
            "prime": o.get("PrimeInformation", {}).get("IsPrime", False),
            "fulfillment": o.get("IsFulfilledByAmazon", False),
            "is_buy_box_winner": o.get("IsBuyBoxWinner", False),
        })
    buy_box = summary.get("BuyBoxPrices", [{}])
    return {
        "ok": True,
        "asin": asin,
        "offer_count": (
            summary.get("TotalOfferCount")
            if summary.get("TotalOfferCount") is not None
            else (sum(o.get("OfferCount", 0) for o in summary.get("NumberOfOffers", []))
                  if isinstance(summary.get("NumberOfOffers"), list)
                  else summary.get("NumberOfOffers"))
        ),
        "buy_box_price": buy_box[0].get("LandedPrice", {}).get("Amount") if buy_box else None,
        "lowest_new": summary.get("LowestPrices", [{}])[0].get("LandedPrice", {}).get("Amount") if summary.get("LowestPrices") else None,
        "competitive_price_threshold": summary.get("CompetitivePriceThreshold", {}).get("Amount"),
        "offers": result_offers,
    }




def parse_product_pricing_response(data: dict[str, Any]) -> dict[str, Any]:
    prices = []
    for item in data.get("payload", []):
        p = item.get("Product", {}).get("Offers", [{}])
        offer = p[0] if p else {}
        prices.append({
            "asin": item.get("ASIN"),
            "status": item.get("status"),
            "buy_box_price": offer.get("BuyingPrice", {}).get("ListingPrice", {}).get("Amount"),
            "currency": offer.get("BuyingPrice", {}).get("ListingPrice", {}).get("CurrencyCode", "USD"),
            "regular_price": offer.get("RegularPrice", {}).get("Amount"),
        })
    return {"ok": True, "count": len(prices), "prices": prices}


_REFERRAL_FEE_TYPES = frozenset({"Commission", "ReferralFee"})
_FBA_FEE_TYPES = frozenset({
    "FBAPerUnitFulfillmentFee", "FBAFees", "FulfillmentFee", "FBAWeightBasedFee",
})


def _empty_sku_bucket() -> dict[str, Any]:
    return {
        "revenue": 0.0, "referral_fee": 0.0, "fba_fee": 0.0,
        "other_fees": 0.0, "refunds": 0.0, "units_shipped": 0,
    }


def _classify_fee(fee_type: str, amt: float, row: dict[str, Any]) -> tuple[float, float, float]:
    """Return (referral, fba, other) increments for a fee line."""
    if fee_type in _REFERRAL_FEE_TYPES:
        row["referral_fee"] += amt
        return amt, 0.0, 0.0
    if fee_type in _FBA_FEE_TYPES:
        row["fba_fee"] += amt
        return 0.0, amt, 0.0
    row["other_fees"] += amt
    return 0.0, 0.0, amt


def _accumulate_shipment_items(
    orders_ev: list[dict[str, Any]], by_sku: dict[str, dict[str, Any]],
) -> tuple[float, float, float, float, float]:
    gross = referral = fba = other_fees = 0.0
    for ev in orders_ev:
        for item in ev.get("ShipmentItemList", []):
            sku = str(item.get("SellerSKU") or "UNKNOWN")
            row = by_sku.setdefault(sku, _empty_sku_bucket())
            row["units_shipped"] += int(item.get("QuantityShipped") or 0)
            for charge in item.get("ItemChargeList", []):
                if charge.get("ChargeType") == "Principal":
                    amt = float(charge.get("ChargeAmount", {}).get("CurrencyAmount", 0) or 0)
                    gross += amt
                    row["revenue"] += amt
            for fee in item.get("ItemFeeList", []):
                amt = abs(float(fee.get("FeeAmount", {}).get("CurrencyAmount", 0) or 0))
                r, f, o = _classify_fee(str(fee.get("FeeType") or ""), amt, row)
                referral += r
                fba += f
                other_fees += o
    return gross, referral, fba, other_fees, 0.0


def _accumulate_refunds(
    refund_ev: list[dict[str, Any]], by_sku: dict[str, dict[str, Any]],
) -> float:
    refunds = 0.0
    for ev in refund_ev:
        for item in ev.get("ShipmentItemAdjustmentList", []):
            sku = str(item.get("SellerSKU") or "UNKNOWN")
            row = by_sku.setdefault(sku, _empty_sku_bucket())
            for charge in item.get("ItemChargeAdjustmentList", []):
                if charge.get("ChargeType") == "Principal":
                    amt = abs(float(charge.get("ChargeAmount", {}).get("CurrencyAmount", 0) or 0))
                    refunds += amt
                    row["refunds"] += amt
    return refunds


def _round_by_sku(by_sku: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        sku: {
            "revenue": round(vals["revenue"], 2),
            "referral_fee": round(vals["referral_fee"], 2),
            "fba_fee": round(vals["fba_fee"], 2),
            "other_fees": round(vals["other_fees"], 2),
            "refunds": round(vals["refunds"], 2),
            "units_shipped": vals["units_shipped"],
        }
        for sku, vals in by_sku.items()
    }


def parse_financial_events_detailed(data: dict[str, Any], days: int) -> dict[str, Any]:
    """Parse Finances v0 events with referral/FBA/refund breakdown and per-SKU totals."""
    events = data.get("payload", {}).get("FinancialEvents", {})
    orders_ev = events.get("ShipmentEventList", [])
    refund_ev = events.get("RefundEventList", [])
    by_sku: dict[str, dict[str, Any]] = {}
    gross, referral, fba, other_fees, _ = _accumulate_shipment_items(orders_ev, by_sku)
    refunds = _accumulate_refunds(refund_ev, by_sku)
    total_fees = referral + fba + other_fees
    return {
        "ok": True, "period_days": days,
        "gross_revenue": round(gross, 2), "total_fees": round(total_fees, 2),
        "refunds": round(refunds, 2),
        "net_proceeds": round(gross - total_fees - refunds, 2),
        "fee_breakdown": {
            "referral": round(referral, 2), "fba": round(fba, 2), "other": round(other_fees, 2),
        },
        "by_sku": _round_by_sku(by_sku),
        "shipment_events": len(orders_ev), "refund_events": len(refund_ev),
    }


def parse_financial_events_response(data: dict[str, Any], days: int) -> dict[str, Any]:
    """Summary financial parse — backward-compatible wrapper over detailed parser."""
    detailed = parse_financial_events_detailed(data, days)
    return {
        "ok": detailed["ok"], "period_days": detailed["period_days"],
        "gross_revenue": detailed["gross_revenue"], "total_fees": detailed["total_fees"],
        "net_proceeds": detailed["net_proceeds"], "refunds": detailed["refunds"],
        "fee_breakdown": detailed["fee_breakdown"], "by_sku": detailed["by_sku"],
        "shipment_events": detailed["shipment_events"], "refund_events": detailed["refund_events"],
    }


def parse_fees_estimate_response(data: dict[str, Any], asin: str, price: float) -> dict[str, Any]:
    fees = data.get("payload", {}).get("FeesEstimateResult", {}).get("FeesEstimate", {})
    total = fees.get("TotalFeesEstimate", {})
    components = fees.get("FeeDetailList", [])
    breakdown = {c.get("FeeType"): c.get("FeeAmount", {}).get("Amount") for c in components}
    total_fees = total.get("Amount", 0)
    return {
        "ok": True, "asin": asin, "sale_price": price,
        "total_fees": total_fees, "fee_breakdown": breakdown,
        "net_revenue": round(price - total_fees, 2),
    }


def _fulfillable_quantity(summary: dict[str, Any]) -> int:
    """Extract fulfillable qty from FBA inventory summary (v1 nested or legacy flat)."""
    if summary.get("fulfillableQuantity") is not None:
        return int(summary.get("fulfillableQuantity") or 0)
    details = summary.get("inventoryDetails") or {}
    return int(details.get("fulfillableQuantity") or 0)


class SPAPIClient:
    """Amazon Selling Partner API client — catalog, orders, inventory, pricing, reports, finance."""

    def __init__(self, cfg: AmazonConfig, auth: LWAAuth, limits: RateLimitRegistry) -> None:
        self.cfg = cfg
        self.auth = auth
        self.limits = limits
        self.base = _SP_ENDPOINTS.get(cfg.sp_region, _SP_ENDPOINTS["na"])
        self._cache = ResponseCache(ttl_seconds=cfg.cache_ttl_seconds)
        # Cache key prefix for tenant isolation (seller_id + marketplace)
        self._ck_prefix = f"{cfg.seller_id or 'default'}:{cfg.marketplace_id}:"

    # ── HTTP helpers ─────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            token = await self.auth.get_access_token()
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.get(
                    f"{self.base}{path}",
                    params=params,
                    headers={"x-amz-access-token": token, "Content-Type": "application/json"},
                )
                raise_on_429(resp)
                return resp.json()
        return await self.limits.call_with_backoff(f"sp:{path}", _do)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            token = await self.auth.get_access_token()
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(
                    f"{self.base}{path}",
                    json=body,
                    headers={"x-amz-access-token": token, "Content-Type": "application/json"},
                )
                raise_on_429(resp)
                return resp.json()
        return await self.limits.call_with_backoff(f"sp:POST:{path}", _do)

    async def _delete(self, path: str) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            token = await self.auth.get_access_token()
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.delete(
                    f"{self.base}{path}",
                    headers={"x-amz-access-token": token, "Content-Type": "application/json"},
                )
                raise_on_429(resp)
                if resp.status_code == 204:
                    return {}
                return resp.json()
        return await self.limits.call_with_backoff(f"sp:DELETE:{path}", _do)

    async def _patch(self, path: str, params: dict[str, str] | None, body: dict[str, Any]) -> dict[str, Any]:
        async def _do() -> dict[str, Any]:
            token = await self.auth.get_access_token()
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.patch(
                    f"{self.base}{path}",
                    params=params,
                    json=body,
                    headers={"x-amz-access-token": token, "Content-Type": "application/json"},
                )
                raise_on_429(resp)
                return resp.json()
        return await self.limits.call_with_backoff(f"sp:PATCH:{path}", _do)

    def _iso(self, days_ago: int) -> str:
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Catalog ──────────────────────────────────────────────────────────────

    async def get_catalog_item(self, asin: str) -> dict[str, Any]:
        """Get detailed catalog info for a single ASIN."""
        _ck = f"{self._ck_prefix}catalog:{asin}"
        cached = self._cache.get(_ck)
        if cached is not CACHE_MISS:
            return cached
        if self.cfg.dry_run:
            data = _load_fixture("sp_api", "catalog_item.json")
            parsed = _parse_catalog_item_data(data, asin, self.cfg.marketplace_id)
            parsed["dry_run"] = True
            self._cache.set(_ck, parsed, ttl_seconds=briefing_cache_ttl("catalog"))
            return parsed
        data = await self._get(
            f"/catalog/2022-04-01/items/{asin}",
            {"marketplaceIds": self.cfg.marketplace_id,
             "includedData": "summaries,attributes,dimensions,identifiers,images,productTypes,relationships,salesRanks,classifications"},
        )
        result = _parse_catalog_item_data(data, asin, self.cfg.marketplace_id)
        self._cache.set(_ck, result, ttl_seconds=briefing_cache_ttl("catalog"))
        return result

    async def search_catalog(self, keywords: str, category: str = "", page_size: int = 20) -> dict[str, Any]:
        """Search catalog items by keywords."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "keywords": keywords,
                "items": [
                    {"asin": "B0DRY0001", "title": f"{keywords} Product A", "brand": "BrandX", "rank": 500},
                    {"asin": "B0DRY0002", "title": f"{keywords} Product B", "brand": "BrandY", "rank": 1200},
                ],
            }
        params: dict[str, str] = {
            "keywords": keywords,
            "marketplaceIds": self.cfg.marketplace_id,
            "includedData": "summaries,salesRanks",
            "pageSize": str(min(page_size, 20)),
        }
        if category:
            params["classificationIds"] = category
        data = await self._get("/catalog/2022-04-01/items", params)
        items = []
        for item in data.get("items", []):
            s = (item.get("summaries") or [{}])[0]
            ranks = (item.get("salesRanks") or [{}])
            rank_val = None
            if ranks:
                r = ranks[0].get("ranks", [])
                if r:
                    rank_val = r[0].get("rank")
            items.append({
                "asin": item.get("asin"),
                "title": s.get("itemName"),
                "brand": s.get("brand"),
                "rank": rank_val,
            })
        return {
            "ok": True, "keywords": keywords, "count": len(items),
            "items": items,
            "pagination": data.get("pagination"),
        }

    async def bulk_catalog_lookup(self, asins: list[str]) -> dict[str, Any]:
        """Fetch multiple ASINs concurrently (max 20)."""
        asins = asins[:20]
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "items": [
                    {"asin": a, "title": f"Product {a} (dry-run)", "brand": "DemoBrand"}
                    for a in asins
                ],
            }
        tasks = [self.get_catalog_item(a) for a in asins]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        items = []
        for asin, res in zip(asins, results):
            if isinstance(res, Exception):
                items.append({"asin": asin, "error": str(res)})
            else:
                items.append(res)
        return {"ok": True, "count": len(items), "items": items}

    # ── Product Pricing ───────────────────────────────────────────────────────

    async def get_product_pricing(self, asins: list[str]) -> dict[str, Any]:
        """Get Buy Box and listing prices for up to 20 ASINs."""
        if not asins:
            return {"ok": True, "prices": []}
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "prices": [
                    {"asin": a, "buy_box_price": 29.99, "lowest_new": 27.49,
                     "your_price": 29.99, "currency": "USD"}
                    for a in asins
                ],
            }
        params = {
            "MarketplaceId": self.cfg.marketplace_id,
            "Asins": ",".join(asins[:20]),
            "ItemType": "Asin",
        }
        data = await self._get("/products/pricing/v0/price", params)
        return parse_product_pricing_response(data)

    async def get_competitive_pricing(self, asin: str) -> dict[str, Any]:
        """Get competitive pricing and all active offers for an ASIN."""
        if self.cfg.dry_run:
            data = _load_fixture("sp_api", "competitive_pricing_offers.json")
            parsed = _parse_competitive_pricing_data(data, asin)
            # ASIN-specific overlay so dry-run scenarios produce distinct health scores
            if asin.upper().endswith("02") and parsed.get("offers"):
                parsed["offers"][0]["price"] = 28.99
                parsed["offers"][0]["is_buy_box_winner"] = True
            elif asin.upper().endswith("01") and parsed.get("offers"):
                parsed["offers"][0]["price"] = 33.50
                parsed["offers"][0]["is_buy_box_winner"] = True
            parsed["dry_run"] = True
            return parsed
        _ck = f"{self._ck_prefix}comp_pricing:{asin}"
        cached = self._cache.get(_ck)
        if cached is not CACHE_MISS:
            return cached
        data = await self._get(
            f"/products/pricing/v0/items/{asin}/offers",
            {"MarketplaceId": self.cfg.marketplace_id, "ItemCondition": "New", "CustomerType": "Consumer"},
        )
        result = _parse_competitive_pricing_data(data, asin)
        self._cache.set(_ck, result, ttl_seconds=briefing_cache_ttl("pricing"))
        return result

    # ── FBA Fees ──────────────────────────────────────────────────────────────

    async def get_fee_estimate(self, asin: str, price: float) -> dict[str, Any]:
        """Estimate FBA fulfillment fees for a given ASIN and sale price."""
        if self.cfg.dry_run:
            ref_price = price
            fba_fee = round(ref_price * 0.15 + 3.00, 2)
            return {
                "ok": True, "dry_run": True, "asin": asin,
                "sale_price": price,
                "total_fees": fba_fee,
                "fee_breakdown": {"referral_fee": round(ref_price * 0.15, 2), "fba_fee": 3.00},
                "net_revenue": round(price - fba_fee, 2),
            }
        body = {
            "FeesEstimateRequest": {
                "MarketplaceId": self.cfg.marketplace_id,
                "IsAmazonFulfilled": True,
                "PriceToEstimateFees": {
                    "ListingPrice": {"CurrencyCode": "USD", "Amount": price},
                    "Shipping": {"CurrencyCode": "USD", "Amount": 0},
                },
                "Identifier": asin,
            }
        }
        data = await self._post(f"/products/fees/v0/items/{asin}/feesEstimate", body)
        return parse_fees_estimate_response(data, asin, price)

    # ── Inventory ─────────────────────────────────────────────────────────────

    async def get_inventory_summaries(self, skus: list[str] | None = None) -> dict[str, Any]:
        """FBA inventory levels with health signals."""
        _ck = self._ck_prefix + "inv_summaries:" + (",".join(sorted(skus)) if skus else "all")
        cached = self._cache.get(_ck)
        if cached is not CACHE_MISS:
            return cached
        if self.cfg.dry_run:
            data = _load_fixture("sp_api", "inventory_summaries.json")
            summaries = data.get("payload", {}).get("inventorySummaries", [])
            if skus:
                sku_set = set(skus)
                summaries = [s for s in summaries if s.get("sellerSku") in sku_set]
            alerts = [s.get("sellerSku") for s in summaries if _fulfillable_quantity(s) < 10]
            result = {"ok": True, "dry_run": True, "summaries": summaries, "low_stock_alerts": alerts}
            self._cache.set(_ck, result, ttl_seconds=briefing_cache_ttl("inventory"))
            return result
        cached = self._cache.get(_ck)
        if cached is not CACHE_MISS:
            return cached

        params: dict[str, str] = {
            "granularityType": "Marketplace",
            "granularityId": self.cfg.marketplace_id,
            "details": "true",
        }
        if skus:
            params["sellerSkus"] = ",".join(skus[:20])
        data = await self._get("/fba/inventory/v1/summaries", params)
        summaries = data.get("payload", {}).get("inventorySummaries", [])
        alerts = [s.get("sellerSku") for s in summaries if _fulfillable_quantity(s) < 10]
        result = {
            "ok": True,
            "count": len(summaries),
            "low_stock_alerts": alerts,
            "summaries": summaries,
        }
        self._cache.set(_ck, result, ttl_seconds=briefing_cache_ttl("inventory"))
        return result

    async def list_inventory_asins(self) -> dict[str, Any]:
        inv = await self.get_inventory_summaries()
        summaries = inv.get("summaries") or []
        asins = [str(s.get("asin")) for s in summaries if s.get("asin")]
        return {
            "ok": True, "dry_run": bool(inv.get("dry_run")),
            "count": len(asins), "asins": asins, "summaries": summaries,
        }

    async def get_inventory_health(self) -> dict[str, Any]:
        """Inventory health summary with restock recommendations."""
        inv = await self.get_inventory_summaries()
        summaries = inv.get("summaries") or []
        total = len(summaries)
        low = [s for s in summaries if (s.get("fulfillableQuantity") or 0) < 10]
        out = [s for s in summaries if (s.get("fulfillableQuantity") or 0) == 0]
        healthy = total - len(low)
        return {
            "ok": True,
            "dry_run": inv.get("dry_run", False),
            "total_skus": total,
            "healthy_count": healthy,
            "low_stock_count": len(low),
            "out_of_stock_count": len(out),
            "low_stock_skus": [s.get("sku") or s.get("sellerSku") for s in low],
            "out_of_stock_skus": [s.get("sku") or s.get("sellerSku") for s in out],
            "restock_recommended": [
                {
                    "sku": s.get("sku") or s.get("sellerSku"),
                    "asin": s.get("asin"),
                    "qty_available": s.get("fulfillableQuantity", 0),
                    "inbound": (s.get("inboundWorkingQuantity") or 0) + (s.get("inboundShippedQuantity") or 0),
                }
                for s in low
            ],
        }

    # ── Orders ────────────────────────────────────────────────────────────────

    async def list_orders(self, days: int = 7, status: str = "", max_results: int = 100) -> dict[str, Any]:
        """List orders from past N days, optionally filtered by status."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "period_days": days,
                "orders": [
                    {"AmazonOrderId": "111-1234567-1234001", "OrderStatus": "Shipped",
                     "OrderTotal": {"CurrencyCode": "USD", "Amount": "49.99"},
                     "NumberOfItemsShipped": 2, "PurchaseDate": "2026-06-10T12:00:00Z",
                     "SalesChannel": "Amazon.com"},
                    {"AmazonOrderId": "111-1234567-1234002", "OrderStatus": "Pending",
                     "OrderTotal": {"CurrencyCode": "USD", "Amount": "24.99"},
                     "NumberOfItemsShipped": 0, "PurchaseDate": "2026-06-13T08:30:00Z",
                     "SalesChannel": "Amazon.com"},
                ],
                "count": 2,
            }
        params: dict[str, str] = {
            "MarketplaceIds": self.cfg.marketplace_id,
            "CreatedAfter": self._iso(days),
            "MaxResultsPerPage": str(min(max_results, 100)),
        }
        if status:
            params["OrderStatuses"] = status
        data = await self._get("/orders/v0/orders", params)
        orders = data.get("payload", {}).get("Orders", [])
        return {
            "ok": True, "count": len(orders), "period_days": days,
            "orders": orders,
            "next_token": data.get("payload", {}).get("NextToken"),
        }

    async def get_order_details(self, order_id: str) -> dict[str, Any]:
        """Get full details for a specific order including line items."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "order": {
                    "AmazonOrderId": order_id, "OrderStatus": "Shipped",
                    "OrderTotal": {"CurrencyCode": "USD", "Amount": "49.99"},
                    "ShipServiceLevel": "Std US D2D Dom", "PaymentMethod": "Other",
                    "PurchaseDate": "2026-06-10T12:00:00Z",
                },
                "items": [
                    {"ASIN": "B0POC00001", "SellerSKU": "SKU-001", "Title": "Sample Product",
                     "QuantityOrdered": 2, "ItemPrice": {"Amount": "49.99", "CurrencyCode": "USD"},
                     "IsGift": False},
                ],
            }
        order_data = await self._get(f"/orders/v0/orders/{order_id}")
        items_data = await self._get(f"/orders/v0/orders/{order_id}/orderItems")
        return {
            "ok": True,
            "order": order_data.get("payload", {}),
            "items": items_data.get("payload", {}).get("OrderItems", []),
        }

    async def get_orders_metrics(self, days: int = 7) -> dict[str, Any]:
        """Aggregate sales metrics from order history."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "period_days": days,
                "orders": 128, "units": 342, "revenue_usd": 18420.55,
                "avg_order_value": 143.91, "cancellation_rate": 0.02,
            }
        orders_resp = await self.list_orders(days, max_results=100)
        orders = orders_resp.get("orders", [])
        total_revenue = 0.0
        total_units = 0
        statuses: dict[str, int] = {}
        for o in orders:
            amt = o.get("OrderTotal", {}).get("Amount")
            if amt:
                try:
                    total_revenue += float(amt)
                except ValueError:
                    pass
            total_units += o.get("NumberOfItemsShipped", 0) or 0
            st = o.get("OrderStatus", "Unknown")
            statuses[st] = statuses.get(st, 0) + 1
        count = len(orders)
        return {
            "ok": True, "period_days": days,
            "orders": count,
            "units": total_units,
            "revenue_usd": round(total_revenue, 2),
            "avg_order_value": round(total_revenue / count, 2) if count else 0,
            "order_statuses": statuses,
        }

    # ── Finances ──────────────────────────────────────────────────────────────

    async def get_financial_events(self, days: int = 30) -> dict[str, Any]:
        """Get financial events (orders, refunds, fees, adjustments) — Finances v0."""
        if self.cfg.dry_run:
            data = _load_fixture("sp_api", "financial_events.json")
            result = parse_financial_events_detailed(data, days)
            result["dry_run"] = True
            return result
        posted_after = self._iso(days)
        data = await self._get("/finances/v0/financialEvents", {"PostedAfter": posted_after})
        return parse_financial_events_detailed(data, days)

    async def get_financial_events_v2(
        self, days: int = 30, *, next_token: str = "", page_size: int = 100,
    ) -> dict[str, Any]:
        """Get itemized financial transactions — Finances v2024-06-19.

        Returns richer per-transaction data: transactionType, marketplace, fee breakdowns.
        Supports pagination via nextToken.
        """
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "postedAfter": self._iso(days),
                "total_transactions": 3,
                "transactions": [
                    {
                        "transactionId": "TX-DRY-001",
                        "transactionType": "Order",
                        "postedDate": self._iso(1),
                        "marketplaceId": self.cfg.marketplace_id,
                        "totalAmount": {"currencyCode": "USD", "currencyAmount": 29.99},
                        "charges": [
                            {"chargeType": "Principal", "chargeAmount": {"currencyCode": "USD", "currencyAmount": 29.99}},
                            {"chargeType": "ShippingCharge", "chargeAmount": {"currencyCode": "USD", "currencyAmount": 0.0}},
                        ],
                        "fees": [
                            {"feeType": "ReferralFee", "feeAmount": {"currencyCode": "USD", "currencyAmount": -4.50}},
                            {"feeType": "FBAPerUnitFulfillmentFee", "feeAmount": {"currencyCode": "USD", "currencyAmount": -3.22}},
                        ],
                        "sellerOrderId": "ORDER-DRY-001",
                        "asin": "B0POC00001",
                    },
                    {
                        "transactionId": "TX-DRY-002",
                        "transactionType": "Refund",
                        "postedDate": self._iso(3),
                        "marketplaceId": self.cfg.marketplace_id,
                        "totalAmount": {"currencyCode": "USD", "currencyAmount": -29.99},
                        "charges": [
                            {"chargeType": "Principal", "chargeAmount": {"currencyCode": "USD", "currencyAmount": -29.99}},
                        ],
                        "fees": [],
                        "sellerOrderId": "ORDER-DRY-002",
                        "asin": "B0POC00002",
                    },
                    {
                        "transactionId": "TX-DRY-003",
                        "transactionType": "ServiceFee",
                        "postedDate": self._iso(7),
                        "marketplaceId": self.cfg.marketplace_id,
                        "totalAmount": {"currencyCode": "USD", "currencyAmount": -39.99},
                        "charges": [],
                        "fees": [
                            {"feeType": "SubscriptionFee", "feeAmount": {"currencyCode": "USD", "currencyAmount": -39.99}},
                        ],
                        "sellerOrderId": None,
                        "asin": None,
                    },
                ],
                "nextToken": None,
                "note": "Finances v2024-06-19 — richer transaction schema vs v0",
            }
        params: dict[str, str] = {
            "PostedAfter": self._iso(days),
            "MaxResultsPerPage": str(page_size),
        }
        if next_token:
            params["NextToken"] = next_token
        data = await self._get("/finances/2024-06-19/financialEvents", params)
        txns = data.get("financialEvents") or data.get("transactions") or []
        return {
            "ok": True,
            "postedAfter": self._iso(days),
            "total_transactions": len(txns),
            "transactions": txns,
            "nextToken": data.get("nextToken"),
        }

    # ── Reports ───────────────────────────────────────────────────────────────

    async def create_report(self, report_type_key: str, days: int = 7) -> dict[str, Any]:
        """Request a report. report_type_key: sales_traffic|inventory|orders|settlement|returns|reimbursements|account_health|inventory_planning|storage_fees."""
        report_type = _REPORT_TYPES.get(report_type_key, report_type_key)
        if self.cfg.dry_run:
            dry_ids = {
                "GET_FBA_REIMBURSEMENTS_DATA": "REPORT-DRY-REIMB",
                "GET_V2_SELLER_PERFORMANCE_REPORT": "REPORT-DRY-PERF",
                "GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA": "REPORT-DRY-RETURNS",
                "GET_FBA_INVENTORY_PLANNING_DATA": "REPORT-DRY-IPI",
                "GET_FBA_STORAGE_FEE_CHARGES_DATA": "REPORT-DRY-STORAGE",
                "GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT": "REPORT-DRY-RESTOCK",
            }
            report_id = dry_ids.get(report_type, "REPORT-DRY-001")
            return {
                "ok": True, "dry_run": True,
                "reportId": report_id,
                "reportType": report_type,
                "processingStatus": "DONE",
                "note": "In dry_run mode; set AMAZON_MCP_DRY_RUN=0 for live reports.",
            }
        body: dict[str, Any] = {
            "reportType": report_type,
            "marketplaceIds": [self.cfg.marketplace_id],
            "dataStartTime": self._iso(days),
            "dataEndTime": self._iso(0),
        }
        data = await self._post("/reports/2021-06-30/reports", body)
        return {
            "ok": True,
            "reportId": data.get("reportId"),
            "reportType": report_type,
            "processingStatus": data.get("processingStatus"),
        }

    async def get_report_status(self, report_id: str) -> dict[str, Any]:
        """Check report processing status."""
        if self.cfg.dry_run:
            doc_ids = {
                "REPORT-DRY-REIMB": "DOC-DRY-REIMB",
                "REPORT-DRY-PERF": "DOC-DRY-PERF",
                "REPORT-DRY-RETURNS": "DOC-DRY-RETURNS",
                "REPORT-DRY-IPI": "DOC-DRY-IPI",
                "REPORT-DRY-STORAGE": "DOC-DRY-STORAGE",
                "REPORT-DRY-RESTOCK": "DOC-DRY-RESTOCK",
            }
            return {
                "ok": True, "dry_run": True, "reportId": report_id,
                "processingStatus": "DONE",
                "reportDocumentId": doc_ids.get(report_id, "DOC-DRY-001"),
            }
        data = await self._get(f"/reports/2021-06-30/reports/{report_id}")
        return {
            "ok": True,
            "reportId": report_id,
            "processingStatus": data.get("processingStatus"),
            "reportDocumentId": data.get("reportDocumentId"),
            "dataStartTime": data.get("dataStartTime"),
            "dataEndTime": data.get("dataEndTime"),
        }

    async def download_report_document(self, document_id: str) -> dict[str, Any]:
        """Download and decompress a report document."""
        if self.cfg.dry_run:
            if document_id == "DOC-DRY-REIMB":
                tsv_path = _FIXTURES_DIR / "sp_api" / "fba_reimbursements.tsv"
                text = tsv_path.read_text(encoding="utf-8")
                lines = text.strip().split("\n")
                return {
                    "ok": True, "dry_run": True, "documentId": document_id,
                    "report_type": "GET_FBA_REIMBURSEMENTS_DATA",
                    "total_lines": len(lines),
                    "preview": "\n".join(lines[:50]),
                    "truncated": len(lines) > 50,
                }
            if document_id == "DOC-DRY-PERF":
                tsv_path = _FIXTURES_DIR / "sp_api" / "seller_performance.tsv"
                text = tsv_path.read_text(encoding="utf-8")
                lines = text.strip().split("\n")
                return {
                    "ok": True, "dry_run": True, "documentId": document_id,
                    "report_type": "GET_V2_SELLER_PERFORMANCE_REPORT",
                    "total_lines": len(lines),
                    "preview": "\n".join(lines[:50]),
                    "truncated": len(lines) > 50,
                }
            if document_id == "DOC-DRY-RETURNS":
                tsv_path = _FIXTURES_DIR / "sp_api" / "fba_returns.tsv"
                text = tsv_path.read_text(encoding="utf-8")
                lines = text.strip().split("\n")
                return {
                    "ok": True, "dry_run": True, "documentId": document_id,
                    "report_type": "GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA",
                    "total_lines": len(lines),
                    "preview": "\n".join(lines[:50]),
                    "truncated": len(lines) > 50,
                }
            if document_id == "DOC-DRY-IPI":
                tsv_path = _FIXTURES_DIR / "sp_api" / "fba_inventory_planning.tsv"
                text = tsv_path.read_text(encoding="utf-8")
                lines = text.strip().split("\n")
                return {
                    "ok": True, "dry_run": True, "documentId": document_id,
                    "report_type": "GET_FBA_INVENTORY_PLANNING_DATA",
                    "total_lines": len(lines),
                    "preview": "\n".join(lines[:50]),
                    "truncated": len(lines) > 50,
                }
            if document_id == "DOC-DRY-STORAGE":
                tsv_path = _FIXTURES_DIR / "sp_api" / "fba_storage_fees.tsv"
                text = tsv_path.read_text(encoding="utf-8")
                lines = text.strip().split("\n")
                return {
                    "ok": True, "dry_run": True, "documentId": document_id,
                    "report_type": "GET_FBA_STORAGE_FEE_CHARGES_DATA",
                    "total_lines": len(lines),
                    "preview": "\n".join(lines[:50]),
                    "truncated": len(lines) > 50,
                }
            if document_id == "DOC-DRY-RESTOCK":
                tsv_path = _FIXTURES_DIR / "sp_api" / "restock_recommendations.tsv"
                text = tsv_path.read_text(encoding="utf-8")
                lines = text.strip().split("\n")
                return {
                    "ok": True, "dry_run": True, "documentId": document_id,
                    "report_type": "GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT",
                    "total_lines": len(lines),
                    "preview": "\n".join(lines[:50]),
                    "truncated": len(lines) > 50,
                }
            return {
                "ok": True, "dry_run": True, "documentId": document_id,
                "preview": "date\tsku\tunits_ordered\tordered_product_sales\n2026-06-01\tSKU-001\t42\t1890.58",
            }
        # Step 1: get presigned URL
        data = await self._get(f"/reports/2021-06-30/documents/{document_id}")
        url = data.get("url")
        compression = data.get("compressionAlgorithm")
        if not url:
            return {"ok": False, "error": "No download URL in response", "raw": data}

        # Step 2: download
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.content

        # Step 3: decompress if needed
        if compression == "GZIP":
            text = gzip.decompress(raw).decode("utf-8", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")

        lines = text.strip().split("\n")
        preview_lines = lines[:50]
        return {
            "ok": True, "documentId": document_id,
            "total_lines": len(lines),
            "preview": "\n".join(preview_lines),
            "truncated": len(lines) > 50,
        }

    async def get_restock_recommendations(self) -> dict[str, Any]:
        """Parse GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT into structured recommendations."""
        if self.cfg.dry_run:
            tsv_path = _FIXTURES_DIR / "sp_api" / "restock_recommendations.tsv"
            text = tsv_path.read_text(encoding="utf-8")
        else:
            report = await self.create_report("restock_recommendations")
            report_id = report.get("reportId", "")
            status = await self.get_report_status(report_id)
            doc_id = status.get("reportDocumentId", "")
            doc = await self.download_report_document(doc_id)
            text = doc.get("preview", "")

        lines = [l for l in text.strip().split("\n") if l.strip()]
        if not lines:
            return {"ok": True, "dry_run": self.cfg.dry_run, "recommendations": [], "summary": {}}

        headers = [h.strip() for h in lines[0].split("\t")]
        recs: list[dict[str, Any]] = []
        for raw_line in lines[1:]:
            cells = raw_line.split("\t")
            row = {headers[i]: cells[i].strip() if i < len(cells) else "" for i in range(len(headers))}
            alert = row.get("alert-type", "").strip()
            if not alert or alert == "No Action Required":
                continue
            days_of_supply_raw = row.get("days-of-supply", "")
            qty_raw = row.get("recommended-replenishment-qty", "")
            avail_raw = row.get("available-quantity", "")
            recs.append({
                "asin": row.get("ASIN", ""),
                "sku": row.get("sku", ""),
                "fnsku": row.get("fnsku", ""),
                "product_name": row.get("product-name", ""),
                "alert_type": alert,
                "available_qty": int(avail_raw) if avail_raw.isdigit() else 0,
                "days_of_supply": int(days_of_supply_raw) if days_of_supply_raw.isdigit() else None,
                "recommended_replenishment_qty": int(qty_raw) if qty_raw.isdigit() else None,
                "your_price": row.get("your-price", ""),
            })

        recs.sort(key=lambda r: (r["days_of_supply"] if r["days_of_supply"] is not None else 999, r.get("sku") or ""))
        out_of_stock = [r for r in recs if r["alert_type"] == "Out of Stock"]
        reorder_now = [r for r in recs if r["alert_type"] == "Reorder Now"]
        low_inventory = [r for r in recs if r["alert_type"] == "Low Inventory"]

        return {
            "ok": True,
            "dry_run": self.cfg.dry_run,
            "total_actionable": len(recs),
            "summary": {
                "out_of_stock": len(out_of_stock),
                "reorder_now": len(reorder_now),
                "low_inventory": len(low_inventory),
            },
            "recommendations": recs,
        }

    async def get_ipi_score(self) -> dict[str, Any]:
        """Extract IPI score from GET_FBA_INVENTORY_PLANNING_DATA report."""
        if self.cfg.dry_run:
            tsv_path = _FIXTURES_DIR / "sp_api" / "fba_inventory_planning.tsv"
            text = tsv_path.read_text(encoding="utf-8")
        else:
            report = await self.create_report("inventory_planning")
            report_id = report.get("reportId", "")
            status = await self.get_report_status(report_id)
            doc_id = status.get("reportDocumentId", "")
            doc = await self.download_report_document(doc_id)
            text = doc.get("preview", "")

        lines = [l for l in text.strip().split("\n") if l.strip()]
        if not lines:
            return {"ok": False, "dry_run": self.cfg.dry_run, "error": "Empty inventory planning report"}

        headers = [h.strip() for h in lines[0].split("\t")]
        ipi_score: int | None = None
        sku_scores: list[dict[str, Any]] = []

        for raw_line in lines[1:]:
            cells = raw_line.split("\t")
            row = {headers[i]: cells[i].strip() if i < len(cells) else "" for i in range(len(headers))}
            ipi_raw = row.get("inventory-performance-index", "")
            score = int(ipi_raw) if ipi_raw.isdigit() else None
            sku = row.get("sku", "").strip()
            if not sku:
                if score is not None:
                    ipi_score = score
            else:
                if score is not None:
                    sku_scores.append({
                        "sku": sku,
                        "asin": row.get("asin", ""),
                        "ipi_score": score,
                        "available": int(row.get("available", "0") or 0),
                    })

        if ipi_score is None and sku_scores:
            ipi_score = max(r["ipi_score"] for r in sku_scores)

        label = "poor" if (ipi_score or 0) < 300 else "at_risk" if (ipi_score or 0) < 400 else "good" if (ipi_score or 0) < 500 else "excellent"
        return {
            "ok": True,
            "dry_run": self.cfg.dry_run,
            "ipi_score": ipi_score,
            "ipi_label": label,
            "threshold_warning": 400,
            "sku_scores": sku_scores,
            "note": "IPI below 400 may trigger Amazon storage restrictions",
        }

    async def get_sales_by_asin(self, days: int = 30) -> dict[str, Any]:
        """Request and poll sales-by-ASIN report (async; may need polling)."""
        _ck = f"{self._ck_prefix}sales_by_asin:{days}"
        cached = self._cache.get(_ck)
        if cached is not CACHE_MISS:
            return cached
        if self.cfg.dry_run:
            data = _load_fixture("sp_api", "sales_by_asin.json")
            key = "7" if days <= 7 else "30"
            asins = data.get(key) or data.get("30") or []
            result = {"ok": True, "dry_run": True, "period_days": days, "asins": asins}
            self._cache.set(_ck, result, ttl_seconds=briefing_cache_ttl("sales_by_asin"))
            return result
        # In production: POST report → poll → download → parse
        report = await self.create_report("sales_traffic", days)
        result = {
            "ok": True,
            "message": "Report requested. Use get_report_status + download_report_document to retrieve data.",
            "reportId": report.get("reportId"),
            "period_days": days,
        }
        self._cache.set(_ck, result, ttl_seconds=briefing_cache_ttl("sales_by_asin"))
        return result

    # ── Listings ──────────────────────────────────────────────────────────────

    # ── Listings Items CRUD (v2021-08-01) ────────────────────────────────────

    def _seller_id(self) -> str:
        return self.cfg.seller_id or os.environ.get("AMAZON_SELLER_ID", "SELLER-DRY")

    async def get_listing_item(self, sku: str) -> dict[str, Any]:
        """GET /listings/2021-08-01/items/{sellerId}/{sku} — current listing details."""
        seller_id = self._seller_id()
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "sku": sku, "seller_id": seller_id,
                "status": "BUYABLE",
                "summaries": [{"marketplaceId": self.cfg.marketplace_id, "status": "BUYABLE",
                                "itemName": f"Dry-run listing {sku}", "asin": "B0POC00001"}],
                "offers": [{"marketplaceId": self.cfg.marketplace_id,
                             "price": {"listingPrice": {"currencyCode": "USD", "amount": "29.99"}},
                             "fulfillmentChannel": "AMAZON_NA"}],
                "attributes": {},
            }
        data = await self._get(
            f"/listings/2021-08-01/items/{seller_id}/{sku}",
            {"marketplaceIds": self.cfg.marketplace_id, "includedData": "summaries,offers,attributes"},
        )
        return {"ok": True, "sku": sku, "seller_id": seller_id, **data}

    async def patch_listing_item(
        self, sku: str, patches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """PATCH /listings/2021-08-01/items/{sellerId}/{sku} — partial update (price, quantity, status)."""
        seller_id = self._seller_id()
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "sku": sku, "seller_id": seller_id,
                "status": "ACCEPTED",
                "submissionId": f"PATCH-DRY-{sku[:8]}",
                "patches_applied": len(patches),
                "issues": [],
            }
        body = {
            "productType": "PRODUCT",
            "patches": patches,
        }
        data = await self._patch(
            f"/listings/2021-08-01/items/{seller_id}/{sku}",
            {"marketplaceIds": self.cfg.marketplace_id},
            body,
        )
        return {
            "ok": True, "sku": sku, "seller_id": seller_id,
            "status": data.get("status", "SUBMITTED"),
            "submissionId": data.get("submissionId"),
            "issues": data.get("issues") or [],
        }

    async def delete_listing_item(self, sku: str) -> dict[str, Any]:
        """DELETE /listings/2021-08-01/items/{sellerId}/{sku} — remove listing."""
        seller_id = self._seller_id()
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "sku": sku, "seller_id": seller_id,
                "status": "DELETED",
                "submissionId": f"DELETE-DRY-{sku[:8]}",
            }
        data = await self._delete(
            f"/listings/2021-08-01/items/{seller_id}/{sku}?marketplaceIds={self.cfg.marketplace_id}"
        )
        return {
            "ok": True, "sku": sku, "seller_id": seller_id,
            "status": data.get("status", "DELETED"),
            "submissionId": data.get("submissionId"),
        }

    async def get_listing_quality(self, asin: str, seller_id: str = "", sku: str = "") -> dict[str, Any]:
        """Get listing quality indicators for an ASIN."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "asin": asin,
                "quality_score": 78,
                "issues": [
                    {"type": "MISSING_IMAGES", "severity": "HIGH", "message": "Less than 6 product images"},
                    {"type": "SHORT_BULLETS", "severity": "MEDIUM", "message": "Bullet points under 150 chars"},
                ],
                "recommendations": [
                    "Add at least 6 high-quality images",
                    "Expand bullet points with more detail",
                    "Add A+ content for better conversion",
                ],
            }
        # Combine catalog + competitive data for quality signals
        catalog = await self.get_catalog_item(asin)
        pricing = await self.get_competitive_pricing(asin)
        issues = []
        score = 100
        raw = catalog.get("raw", {})
        images = raw.get("images", [])
        if isinstance(images, list) and len(images) < 6:
            issues.append({"type": "LOW_IMAGE_COUNT", "severity": "HIGH",
                           "message": f"Only {len(images)} images; recommend 6+"})
            score -= 15
        if not catalog.get("brand"):
            issues.append({"type": "MISSING_BRAND", "severity": "HIGH", "message": "No brand registered"})
            score -= 10
        offer_count = pricing.get("offer_count") or 0
        if isinstance(offer_count, int) and offer_count > 5:
            issues.append({"type": "HIGH_COMPETITION", "severity": "INFO",
                           "message": f"{offer_count} active offers on this ASIN"})
            score -= 5
        return {
            "ok": True, "asin": asin,
            "quality_score": max(0, score),
            "issues": issues,
            "title": catalog.get("title"),
            "brand": catalog.get("brand"),
            "rank": catalog.get("rank"),
            "category": catalog.get("category"),
            "offer_count": offer_count,
        }

    # ── Brand Analytics (intel P1) ────────────────────────────────────────────

    async def get_brand_analytics_report(self, report_type: str = "search_performance",
                                          period: str = "WEEK", days: int = 7) -> dict[str, Any]:
        """
        Request a Brand Analytics report via Reports API.
        Requires Brand Analytics role in Seller Central.

        report_type options:
          search_performance  → GET_BRAND_ANALYTICS_SEARCH_CATALOG_PERFORMANCE_REPORT
          market_basket       → GET_BRAND_ANALYTICS_MARKET_BASKET_REPORT
          repeat_purchase     → GET_BRAND_ANALYTICS_REPEAT_PURCHASE_REPORT
          demographics        → GET_BRAND_ANALYTICS_DEMOGRAPHICS_REPORT
        """
        _BA_TYPES = {
            "search_performance": "GET_BRAND_ANALYTICS_SEARCH_CATALOG_PERFORMANCE_REPORT",
            "market_basket": "GET_BRAND_ANALYTICS_MARKET_BASKET_REPORT",
            "repeat_purchase": "GET_BRAND_ANALYTICS_REPEAT_PURCHASE_REPORT",
            "demographics": "GET_BRAND_ANALYTICS_DEMOGRAPHICS_REPORT",
            # Two additional types — item competition & lost conversions
            "item_comparison": "GET_BRAND_ANALYTICS_ITEM_COMPARISON_REPORT",
            "alternate_purchase": "GET_BRAND_ANALYTICS_ALTERNATE_PURCHASE_REPORT",
        }
        report_type_id = _BA_TYPES.get(report_type, report_type)
        _BA_DRY_PREVIEWS: dict[str, dict] = {
            "GET_BRAND_ANALYTICS_ITEM_COMPARISON_REPORT": {
                "asin": "B0POC00001", "comparedAsin": "B0COMP001",
                "viewSharePct": 0.12, "purchaseSharePct": 0.08,
            },
            "GET_BRAND_ANALYTICS_ALTERNATE_PURCHASE_REPORT": {
                "asin": "B0POC00001", "alternatePurchaseAsin": "B0ALT001",
                "alternatePurchaseCount": 142, "comparisonPurchaseCount": 89,
            },
        }
        if self.cfg.dry_run:
            preview = _BA_DRY_PREVIEWS.get(report_type_id, {
                "searchTerm": "mcp server amazon",
                "searchFrequencyRank": 12340,
                "clickedAsin_1": "B0POC00001",
                "clickShare_1": "0.32",
                "conversionShare_1": "0.28",
            })
            return {
                "ok": True, "dry_run": True,
                "reportType": report_type_id,
                "reportId": "BA-REPORT-DRY-001",
                "processingStatus": "DONE",
                "preview": preview,
            }
        body: dict[str, Any] = {
            "reportType": report_type_id,
            "marketplaceIds": [self.cfg.marketplace_id],
            "dataStartTime": self._iso(days),
            "dataEndTime": self._iso(0),
            "reportOptions": {"reportPeriod": period},
        }
        data = await self._post("/reports/2021-06-30/reports", body)
        return {
            "ok": True,
            "reportId": data.get("reportId"),
            "reportType": report_type_id,
            "processingStatus": data.get("processingStatus"),
            "note": "Poll with get_report_status, then download_report_document to retrieve data.",
        }

    # ── FBA Inbound v2024-03-20 (intel P0 — v0 deprecated) ───────────────────

    async def create_inbound_plan(self, items: list[dict[str, Any]],
                                   source_address: dict[str, str],
                                   plan_name: str = "") -> dict[str, Any]:
        """
        Create FBA inbound shipment plan using v2024-03-20 API (v0 is deprecated).

        items: list of {"msku": str, "quantity": int, "prepOwner": "AMAZON"|"SELLER"}
        source_address: {"name", "addressLine1", "city", "stateOrProvinceCode",
                         "postalCode", "countryCode"}
        """
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "inboundPlanId": "FBA-PLAN-DRY-001",
                "operationId": "OP-DRY-001",
                "status": "CREATED",
                "destinationFc": "LAX9",
                "note": "v2024-03-20 API — async; poll with get_inbound_operation_status",
            }
        body: dict[str, Any] = {
            "inboundPlanName": plan_name or f"Plan_{self._iso(0)}",
            "sourceAddress": source_address,
            "items": [
                {
                    "msku": item["msku"],
                    "quantity": item["quantity"],
                    "prepOwner": item.get("prepOwner", "SELLER"),
                    "labelOwner": item.get("labelOwner", "SELLER"),
                }
                for item in items
            ],
        }
        data = await self._post("/inbound/fba/2024-03-20/inboundPlans", body)
        return {
            "ok": True,
            "inboundPlanId": data.get("inboundPlanId"),
            "operationId": data.get("operationId"),
            "status": "CREATED",
        }

    async def get_inbound_plan(self, inbound_plan_id: str) -> dict[str, Any]:
        """Get FBA inbound plan status and details (v2024-03-20)."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "inboundPlanId": inbound_plan_id,
                "status": "ACTIVE",
                "shipmentIds": ["SHP-DRY-001", "SHP-DRY-002"],
                "createdAt": "2026-06-14T00:00:00Z",
            }
        data = await self._get(f"/inbound/fba/2024-03-20/inboundPlans/{inbound_plan_id}")
        return {"ok": True, "plan": data}

    async def get_inbound_operation_status(self, operation_id: str) -> dict[str, Any]:
        """Poll async inbound operation status (v2024-03-20)."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "operationId": operation_id,
                "operationStatus": "SUCCESS",
                "operationProblems": [],
            }
        data = await self._get(f"/inbound/fba/2024-03-20/operations/{operation_id}")
        return {
            "ok": True,
            "operationId": operation_id,
            "operationStatus": data.get("operationStatus"),
            "operationProblems": data.get("operationProblems", []),
        }

    # ── Data Kiosk API (GraphQL analytics engine, 2023+) ─────────────────────

    async def create_data_kiosk_query(self, query: str) -> dict[str, Any]:
        """
        Submit a GraphQL query to Data Kiosk API (v2023-11-15).
        Provides high-volume analytics: sales, traffic, brand analytics via GraphQL.
        Returns queryId to poll with get_data_kiosk_query_status.

        Example query:
          query MyQuery {
            analytics_salesAndTraffic_2024_09_30 {
              salesAndTrafficByDate(startDate: "2024-01-01" endDate: "2024-01-31"
                                   granularity: DAY) {
                date orderedProductSales { amount currencyCode }
                orderedProductSalesB2B { amount currencyCode }
                unitsOrdered browserPageViews browserSessions
              }
            }
          }
        """
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "queryId": "DK-QUERY-DRY-001",
                "processingStatus": "IN_PROGRESS",
                "note": "Data Kiosk API 2023-11-15 — GraphQL analytics engine",
            }
        body = {"query": query}
        data = await self._post("/dataKiosk/2023-11-15/queries", body)
        return {
            "ok": True,
            "queryId": data.get("queryId"),
            "processingStatus": data.get("processingStatus"),
        }

    async def get_data_kiosk_query_status(self, query_id: str) -> dict[str, Any]:
        """Poll Data Kiosk query status. When DONE, use documentId to download."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "queryId": query_id,
                "processingStatus": "DONE",
                "dataDocumentId": "DK-DOC-DRY-001",
            }
        data = await self._get(f"/dataKiosk/2023-11-15/queries/{query_id}")
        return {
            "ok": True,
            "queryId": query_id,
            "processingStatus": data.get("processingStatus"),
            "dataDocumentId": data.get("dataDocumentId"),
            "pagination": data.get("pagination"),
        }

    async def get_sales_traffic_kiosk(self, days: int = 30, granularity: str = "DAY") -> dict[str, Any]:
        """
        High-level sales & traffic query via Data Kiosk (recommended over Reports API for analytics).
        granularity: DAY | WEEK | MONTH
        Returns orderedProductSales, unitsOrdered, sessions, pageViews per period.
        """
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "period_days": days, "granularity": granularity,
                "data": [
                    {"date": "2026-06-08", "orderedProductSales": {"amount": 3420.50, "currencyCode": "USD"},
                     "unitsOrdered": 84, "sessions": 1203, "pageViews": 1890,
                     "buyBoxPercentage": 0.94, "unitSessionPercentage": 0.070},
                    {"date": "2026-06-09", "orderedProductSales": {"amount": 2980.20, "currencyCode": "USD"},
                     "unitsOrdered": 71, "sessions": 1050, "pageViews": 1620,
                     "buyBoxPercentage": 0.92, "unitSessionPercentage": 0.068},
                ],
                "note": "Data Kiosk API v2023-11-15 — GraphQL analytics",
            }
        end = self._iso(0)[:10]
        start = self._iso(days)[:10]
        gql = f"""query {{
  analytics_salesAndTraffic_2024_09_30 {{
    salesAndTrafficByDate(startDate: "{start}" endDate: "{end}" granularity: {granularity}) {{
      date
      orderedProductSales {{ amount currencyCode }}
      unitsOrdered
      browserSessions
      browserPageViews
      buyBoxPercentage
      unitSessionPercentage
    }}
  }}
}}"""
        result = await self.create_data_kiosk_query(gql)
        return {
            "ok": True,
            "queryId": result.get("queryId"),
            "processingStatus": result.get("processingStatus"),
            "period_days": days,
            "granularity": granularity,
            "note": "Poll with get_data_kiosk_query_status, then download_report_document.",
        }

    # ── Seller Feedback ───────────────────────────────────────────────────────

    async def get_seller_feedback(self, days: int = 90) -> dict[str, Any]:
        """Get seller feedback ratings and recent comments."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "feedback_summary": {
                    "lifetime_rating": 4.8,
                    "positive_30d": 142, "neutral_30d": 3, "negative_30d": 1,
                    "positive_90d": 412, "neutral_90d": 8, "negative_90d": 4,
                    "positive_365d": 1840, "neutral_365d": 22, "negative_365d": 11,
                },
                "recent_negative": [
                    {"rating": 1, "comments": "Item arrived damaged", "date": "2026-06-10",
                     "order_id": "111-1234567-0001234"},
                ],
            }
        data = await self._get(
            "/seller-feedback/v1/ratings",
            {"marketplaceId": self.cfg.marketplace_id},
        )
        return {"ok": True, "feedback": data}

    # ── Notifications ─────────────────────────────────────────────────────────

    async def list_notification_subscriptions(self, notification_type: str = "ORDER_CHANGE") -> dict[str, Any]:
        """
        List active notification subscriptions.
        notification_type options: ORDER_CHANGE | ITEM_PRODUCT_TYPE_CHANGE |
          LISTINGS_ITEM_STATUS_CHANGE | LISTINGS_ITEM_ISSUES_CHANGE | FBA_OUTBOUND_SHIPMENT_STATUS
        """
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "notificationType": notification_type,
                "subscriptions": [
                    {"subscriptionId": "SUB-DRY-001", "payloadVersion": "1.0",
                     "destinationId": "DEST-DRY-001", "processingDirective": {}},
                ],
                "note": "Notifications require external SQS/EventBridge destination setup",
            }
        data = await self._get(f"/notifications/v1/subscriptions/{notification_type}")
        return {
            "ok": True,
            "notificationType": notification_type,
            "subscriptions": data.get("payload", {}).get("subscriptions", []),
        }

    async def create_notification_destination(self, name: str, webhook_url: str) -> dict[str, Any]:
        """Register webhook destination for Notifications API (HTTPS required in live mode)."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "destinationId": "DEST-DRY-WEBHOOK-001",
                "name": name,
                "resource": {"eventBridge": None, "sqs": None, "webhook": {"url": webhook_url}},
            }
        body = {
            "name": name,
            "resourceSpecification": {
                "webhook": {
                    "url": webhook_url,
                    "authorizationMethod": "NONE",
                }
            },
        }
        data = await self._post("/notifications/v1/destinations", body)
        return {"ok": True, "destinationId": data.get("destinationId"), "raw": data}

    async def create_notification_subscription(
        self, notification_type: str, destination_id: str, *, payload_version: str = "1.0",
    ) -> dict[str, Any]:
        """Subscribe to a notification type (e.g. ANY_OFFER_CHANGED)."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "notificationType": notification_type,
                "subscriptionId": f"SUB-DRY-{notification_type[:8]}",
                "destinationId": destination_id,
                "payloadVersion": payload_version,
            }
        body = {"destinationId": destination_id, "payloadVersion": payload_version}
        data = await self._post(f"/notifications/v1/subscriptions/{notification_type}", body)
        return {
            "ok": True,
            "notificationType": notification_type,
            "subscriptionId": data.get("subscriptionId"),
            "destinationId": destination_id,
        }


    async def subscribe_notification(
        self, notification_type: str, webhook_url: str, *, destination_name: str | None = None,
    ) -> dict[str, Any]:
        """Create destination + subscription for any SP-API notification type."""
        name = destination_name or f"amazon-mcp-{notification_type.lower().replace('_', '-')[:40]}"
        dest = await self.create_notification_destination(name, webhook_url)
        if not dest.get("ok"):
            return dest
        sub = await self.create_notification_subscription(notification_type, dest["destinationId"])
        return {
            "ok": True,
            "dry_run": dest.get("dry_run", False),
            "destinationId": dest.get("destinationId"),
            "subscriptionId": sub.get("subscriptionId"),
            "notificationType": notification_type,
            "webhook_url": webhook_url,
            "note": "Live mode requires publicly reachable HTTPS endpoint.",
        }

    async def subscribe_any_offer_changed(self, webhook_url: str) -> dict[str, Any]:
        """Convenience: create destination + ANY_OFFER_CHANGED subscription."""
        return await self.subscribe_notification(
            "ANY_OFFER_CHANGED", webhook_url, destination_name="amazon-mcp-offer-webhook",
        )

    async def subscribe_fba_inventory_availability_changes(self, webhook_url: str) -> dict[str, Any]:
        """Convenience: create destination + FBA_INVENTORY_AVAILABILITY_CHANGES subscription."""
        return await self.subscribe_notification(
            "FBA_INVENTORY_AVAILABILITY_CHANGES",
            webhook_url,
            destination_name="amazon-mcp-fba-inventory-webhook",
        )

    async def subscribe_listings_item_status_change(self, webhook_url: str) -> dict[str, Any]:
        """Convenience: subscribe to LISTINGS_ITEM_STATUS_CHANGE — listing active/inactive/suppressed."""
        return await self.subscribe_notification(
            "LISTINGS_ITEM_STATUS_CHANGE",
            webhook_url,
            destination_name="amazon-mcp-listings-status-webhook",
        )

    async def subscribe_listings_item_issues_change(self, webhook_url: str) -> dict[str, Any]:
        """Convenience: subscribe to LISTINGS_ITEM_ISSUES_CHANGE — listing compliance/attribute issues."""
        return await self.subscribe_notification(
            "LISTINGS_ITEM_ISSUES_CHANGE",
            webhook_url,
            destination_name="amazon-mcp-listings-issues-webhook",
        )

    async def subscribe_pricing_health(self, webhook_url: str) -> dict[str, Any]:
        """Convenience: subscribe to PRICING_HEALTH — buy box health and pricing alerts."""
        return await self.subscribe_notification(
            "PRICING_HEALTH",
            webhook_url,
            destination_name="amazon-mcp-pricing-health-webhook",
        )

    async def delete_notification_subscription(
        self, notification_type: str, subscription_id: str,
    ) -> dict[str, Any]:
        """Delete (unsubscribe) a notification subscription by ID."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "notificationType": notification_type,
                "subscriptionId": subscription_id,
                "status": "deleted",
            }
        await self._delete(f"/notifications/v1/subscriptions/{notification_type}/{subscription_id}")
        return {
            "ok": True,
            "notificationType": notification_type,
            "subscriptionId": subscription_id,
            "status": "deleted",
        }

    # ── Stranded / Suppressed Inventory (Reports API) ─────────────────────────

    async def get_stranded_inventory_report(self) -> dict[str, Any]:
        """
        Request stranded inventory report — ASINs in FBA with no active listing.
        Common cause of storage fees without sales. Uses Reports API.
        """
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "reportId": "STRANDED-REPORT-DRY-001",
                "reportType": "GET_STRANDED_INVENTORY_UI_DATA",
                "note": "In live mode: poll get_report_status then download_report_document",
                "example_stranded": [
                    {"sku": "SKU-OLD-001", "asin": "B0OLD0001", "fnsku": "X999A",
                     "quantity": 23, "reason": "Listing suppressed — missing required attribute"},
                ],
            }
        body: dict[str, Any] = {
            "reportType": "GET_STRANDED_INVENTORY_UI_DATA",
            "marketplaceIds": [self.cfg.marketplace_id],
        }
        data = await self._post("/reports/2021-06-30/reports", body)
        return {
            "ok": True,
            "reportId": data.get("reportId"),
            "reportType": "GET_STRANDED_INVENTORY_UI_DATA",
            "processingStatus": data.get("processingStatus"),
        }

    async def get_suppressed_listings_report(self) -> dict[str, Any]:
        """
        Request suppressed listings report — active SKUs hidden from search results.
        Contains reason codes and fix guidance per listing.
        """
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "reportId": "SUPPRESSED-REPORT-DRY-001",
                "reportType": "GET_MERCHANTS_LISTINGS_FYP_REPORT",
                "example_suppressed": [
                    {"sku": "SKU-002", "asin": "B0POC00002", "reason": "MISSING_BULLET_POINTS",
                     "fix": "Add 5 bullet points to listing"},
                ],
            }
        body: dict[str, Any] = {
            "reportType": "GET_MERCHANTS_LISTINGS_FYP_REPORT",
            "marketplaceIds": [self.cfg.marketplace_id],
        }
        data = await self._post("/reports/2021-06-30/reports", body)
        return {
            "ok": True,
            "reportId": data.get("reportId"),
            "reportType": "GET_MERCHANTS_LISTINGS_FYP_REPORT",
        }

    # ── Orders Pagination ─────────────────────────────────────────────────────

    async def list_orders_page(self, next_token: str) -> dict[str, Any]:
        """Fetch next page of orders using next_token from list_orders response."""
        if self.cfg.dry_run:
            return {"ok": True, "dry_run": True, "orders": [], "next_token": None,
                    "note": "No more pages in dry-run mode"}
        data = await self._get("/orders/v0/orders", {"NextToken": next_token,
                                                       "MarketplaceIds": self.cfg.marketplace_id})
        orders = data.get("payload", {}).get("Orders", [])
        return {
            "ok": True,
            "count": len(orders),
            "orders": orders,
            "next_token": data.get("payload", {}).get("NextToken"),
        }

    # ── Marketplace Participations ────────────────────────────────────────────

    async def get_marketplace_participations(self) -> dict[str, Any]:
        """List all marketplaces this seller participates in with IDs and countries."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "marketplaces": [
                    {"id": "ATVPDKIKX0DER", "name": "Amazon.com", "country": "US", "defaultCurrency": "USD"},
                    {"id": "A2EUQ1WTGCTBG2", "name": "Amazon.ca", "country": "CA", "defaultCurrency": "CAD"},
                ],
            }
        data = await self._get("/sellers/v1/marketplaceParticipations")
        participations = data.get("payload", [])
        markets = [
            {
                "id": p.get("marketplace", {}).get("id"),
                "name": p.get("marketplace", {}).get("name"),
                "country": p.get("marketplace", {}).get("countryCode"),
                "defaultCurrency": p.get("marketplace", {}).get("defaultCurrencyCode"),
                "participating": p.get("participation", {}).get("isParticipating", True),
            }
            for p in participations
        ]
        return {"ok": True, "count": len(markets), "marketplaces": markets}
