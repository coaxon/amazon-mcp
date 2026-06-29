"""amazon_catalog domain handlers."""
from __future__ import annotations

from typing import Any

from amazon_mcp.refiner.dom_refiner import refine_product, refine_search_results
from amazon_mcp.tools.deps import ctx_from_params, get_tool_deps, tenant_id_from_params
from amazon_mcp.tools.helpers import sp_json


async def lookup(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    asin = str(params.get("asin", "")).strip().upper()
    raw = await sp.get_catalog_item(asin)
    return refine_product(raw)


async def bulk_lookup(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    asins = str(params.get("asins", ""))
    asin_list = [a.strip().upper() for a in asins.split(",") if a.strip()]
    return await sp_json(sp.bulk_catalog_lookup(asin_list), "bulk_product_lookup")


async def search(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    keywords = str(params.get("keywords", ""))
    category = str(params.get("category", "") or "")
    page_size = int(params.get("page_size", 20))
    raw = await sp.search_catalog(keywords, category, page_size)
    return refine_search_results(raw)


async def listing_quality(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    asin = str(params.get("asin", "")).strip().upper()
    return await sp_json(sp.get_listing_quality(asin), "get_listing_quality")


async def competitor_insights(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    cfg, sp, _ = ctx_from_params(params)
    asin = str(params.get("asin", "")).strip().upper()
    category = str(params.get("category", "") or "")
    product = await sp.get_catalog_item(asin)
    pricing = await sp.get_competitive_pricing(asin)
    offers = pricing.get("offers", [])
    prices = [float(o["price"]) for o in offers if o.get("price") is not None]
    buy_box = pricing.get("buy_box_price")

    your_offer = next((o for o in offers if o.get("is_buy_box_winner")), offers[0] if offers else None)
    your_price = float(your_offer["price"]) if your_offer and your_offer.get("price") is not None else None

    browse_path = product.get("category_browse_path") or []
    category_path_names = [n.get("displayName") for n in browse_path if n.get("displayName")]

    return {
        "ok": True,
        "asin": asin,
        "dry_run": cfg.dry_run,
        "product": {
            "title": product.get("title"),
            "brand": product.get("brand"),
            "rank": product.get("rank"),
            "category": product.get("category") or category,
            "leaf_classification_id": product.get("leaf_classification_id"),
        },
        "category_browse_tree": {
            "path": browse_path,
            "path_names": category_path_names,
            "depth": len(browse_path),
            "root": browse_path[0] if browse_path else None,
            "leaf": browse_path[-1] if browse_path else product.get("browse_classification"),
        },
        "pricing": {
            "buy_box_price": buy_box,
            "your_price": your_price,
            "price_gap_vs_buybox": round(your_price - float(buy_box), 2) if your_price is not None and buy_box is not None else None,
            "lowest_offer": min(prices) if prices else None,
            "highest_offer": max(prices) if prices else None,
            "avg_offer_price": round(sum(prices) / len(prices), 2) if prices else None,
            "competitive_price_threshold": pricing.get("competitive_price_threshold"),
        },
        "competition": {
            "total_offers": pricing.get("offer_count"),
            "prime_offers": sum(1 for o in offers if o.get("prime")),
            "fba_offers": sum(1 for o in offers if o.get("fulfillment")),
            "buy_box_winner": your_offer.get("seller") if your_offer else None,
            "top_offers": offers[:5],
        },
    }


HANDLERS = {
    "lookup": lookup,
    "bulk_lookup": bulk_lookup,
    "search": search,
    "listing_quality": listing_quality,
    "competitor_insights": competitor_insights,
}
