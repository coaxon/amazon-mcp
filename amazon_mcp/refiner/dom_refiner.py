"""Domain refiner — compress verbose SP/Ads JSON to token-efficient payloads."""
from __future__ import annotations

from typing import Any


def _num(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _int(val: Any) -> int | None:
    n = _num(val)
    return int(n) if n is not None else None


def refine_product(raw: dict[str, Any]) -> dict[str, Any]:
    """Catalog product → core merchandising fields only."""
    return {
        "ok": raw.get("ok", True),
        "asin": raw.get("asin"),
        "title": raw.get("title"),
        "brand": raw.get("brand"),
        "price": _num(raw.get("price") or raw.get("list_price")),
        "buybox_winner": raw.get("buybox_winner") or raw.get("buy_box_winner"),
        "buybox_pct": _num(raw.get("buybox_pct") or raw.get("buy_box_pct")),
        "sales_rank": _int(raw.get("sales_rank") or raw.get("rank")),
        "review_count": _int(raw.get("review_count") or raw.get("reviews")),
        "rating": _num(raw.get("rating") or raw.get("star_rating")),
    }


def refine_inventory(raw: dict[str, Any]) -> dict[str, Any]:
    """Inventory summaries → per-SKU essentials + days remaining."""
    rows: list[dict[str, Any]] = []
    for s in raw.get("summaries") or raw.get("inventorySummaries") or []:
        if not isinstance(s, dict):
            continue
        fulfillable = _int(
            s.get("fulfillable_qty")
            or s.get("fulfillableQuantity")
            or s.get("fulfillable")
        )
        inbound = _int(
            s.get("inbound_qty")
            or (s.get("inboundWorkingQuantity") or 0)
            + (s.get("inboundShippedQuantity") or 0)
            + (s.get("inboundReceivingQuantity") or 0)
        )
        daily = _num(s.get("daily_rate") or s.get("daily_sales_rate"))
        days_remaining = None
        if fulfillable is not None and daily and daily > 0:
            days_remaining = round(fulfillable / daily, 1)
        rows.append({
            "sku": s.get("sku") or s.get("sellerSku"),
            "asin": s.get("asin"),
            "fulfillable_qty": fulfillable,
            "inbound_qty": inbound,
            "inventory_days_remaining": days_remaining,
        })
    out: dict[str, Any] = {"ok": raw.get("ok", True), "items": rows, "count": len(rows)}
    if raw.get("dry_run") is not None:
        out["dry_run"] = raw.get("dry_run")
    if raw.get("low_stock_alerts"):
        out["low_stock_alerts"] = raw.get("low_stock_alerts")
    return out


def refine_pricing(raw: dict[str, Any]) -> dict[str, Any]:
    """Pricing response → buy box essentials per ASIN."""
    rows: list[dict[str, Any]] = []
    for p in raw.get("prices") or raw.get("payload") or []:
        if not isinstance(p, dict):
            continue
        offers = p.get("offers") or []
        competitor_count = _int(p.get("competitor_count") or p.get("offer_count") or len(offers))
        rows.append({
            "asin": p.get("asin") or p.get("ASIN"),
            "our_price": _num(p.get("our_price") or p.get("your_price")),
            "lowest_competitor": _num(p.get("lowest_competitor") or p.get("lowest_new")),
            "buybox_price": _num(p.get("buybox_price") or p.get("buy_box_price")),
            "buybox_winner": p.get("buybox_winner") or p.get("buy_box_winner"),
            "competitor_count": competitor_count,
        })
    return {"ok": raw.get("ok", True), "prices": rows, "count": len(rows)}


def refine_ads(raw: dict[str, Any]) -> dict[str, Any]:
    """Ads performance blob → campaign KPIs + top keywords."""
    keywords = raw.get("keyword_top10") or raw.get("top_keywords") or []
    if isinstance(keywords, dict):
        keywords = list(keywords.values())[:10]
    keyword_top10 = []
    for kw in (keywords or [])[:10]:
        if isinstance(kw, dict):
            keyword_top10.append({
                "keyword": kw.get("keyword") or kw.get("term"),
                "spend": _num(kw.get("spend")),
                "sales": _num(kw.get("sales")),
                "acos": _num(kw.get("acos")),
            })
        elif isinstance(kw, str):
            keyword_top10.append({"keyword": kw})
    return {
        "ok": raw.get("ok", True),
        "campaign_name": raw.get("campaign_name") or raw.get("name"),
        "spend": _num(raw.get("spend")),
        "sales": _num(raw.get("sales")),
        "acos": _num(raw.get("acos")),
        "roas": _num(raw.get("roas")),
        "impressions": _int(raw.get("impressions")),
        "clicks": _int(raw.get("clicks")),
        "ctr": _num(raw.get("ctr")),
        "keyword_top10": keyword_top10,
    }


def refine_order_summary(raw: dict[str, Any]) -> dict[str, Any]:
    """Orders/revenue aggregate → headline metrics."""
    orders = raw.get("orders") or raw.get("order_items") or []
    total_revenue = _num(raw.get("total_revenue") or raw.get("revenue"))
    if total_revenue is None and orders:
        total_revenue = sum(_num(o.get("total") or o.get("amount")) or 0 for o in orders if isinstance(o, dict))
    orders_count = _int(raw.get("orders_count") or raw.get("order_count") or len(orders))
    avg_order_value = _num(raw.get("avg_order_value"))
    if avg_order_value is None and orders_count and total_revenue:
        avg_order_value = round(total_revenue / orders_count, 2)
    top_asin = raw.get("top_asin")
    if not top_asin and isinstance(orders, list):
        by_asin: dict[str, float] = {}
        for o in orders:
            if isinstance(o, dict) and o.get("asin"):
                by_asin[str(o["asin"])] = by_asin.get(str(o["asin"]), 0) + (_num(o.get("quantity")) or 1)
        if by_asin:
            top_asin = max(by_asin, key=by_asin.get)
    return {
        "ok": raw.get("ok", True),
        "orders_count": orders_count,
        "total_revenue": total_revenue,
        "avg_order_value": avg_order_value,
        "top_asin": top_asin,
    }


def refine_competitive(raw: dict[str, Any]) -> dict[str, Any]:
    """Competitive pricing → buy box share and price gap."""
    our = _num(raw.get("our_price") or raw.get("your_price"))
    lowest = _num(raw.get("lowest_competitor_price") or raw.get("lowest_price") or raw.get("lowest_new"))
    buybox = _num(raw.get("buybox_price") or raw.get("buy_box_price"))
    price_gap_pct = None
    if our and lowest and our > 0:
        price_gap_pct = round((our - lowest) / our * 100, 2)
    return {
        "ok": raw.get("ok", True),
        "asin": raw.get("asin"),
        "our_buybox_pct": _num(raw.get("our_buybox_pct") or raw.get("buybox_pct")),
        "competitor_count": _int(raw.get("competitor_count") or raw.get("offer_count")),
        "lowest_competitor_price": lowest,
        "price_gap_pct": price_gap_pct,
        "buybox_price": buybox,
    }


def refine_search_results(raw: dict[str, Any]) -> dict[str, Any]:
    """Search catalog → compact item list."""
    items = []
    for item in raw.get("items") or []:
        if isinstance(item, dict):
            items.append(refine_product(item))
    return {
        "ok": raw.get("ok", True),
        "keywords": raw.get("keywords"),
        "count": len(items),
        "items": items,
    }
