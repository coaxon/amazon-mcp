"""amazon_pricing domain handlers."""
from __future__ import annotations

from typing import Any

from amazon_mcp.refiner.dom_refiner import refine_pricing
from amazon_mcp.tools.deps import ctx_from_params, get_tool_deps, tenant_id_from_params
from amazon_mcp.tools.helpers import sp_json
from amazon_mcp.tools.validators import require_positive_price, require_valid_asin


async def product_pricing(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    asins = str(params.get("asins", ""))
    asin_list = [a.strip().upper() for a in asins.split(",") if a.strip()]
    raw = await sp.get_product_pricing(asin_list)
    return refine_pricing(raw)


async def competitive_offers(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    asin = str(params.get("asin", "")).strip().upper()
    return await sp_json(sp.get_competitive_pricing(asin), "get_competitive_offers")


async def fee_estimate(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    asin = str(params.get("asin", "")).strip().upper()
    price = float(params.get("price", 0))
    if err := require_valid_asin(asin):
        return err
    if err := require_positive_price(price):
        return err
    return await sp_json(sp.get_fee_estimate(asin, price), "get_fee_estimate")


async def profit_analysis(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    asin = str(params.get("asin", "")).strip().upper()
    sale_price = float(params.get("sale_price", 0))
    cogs = float(params.get("cogs", 0.0))
    days = int(params.get("days", 30))
    if err := require_valid_asin(asin):
        return err
    if err := require_positive_price(sale_price, "sale_price"):
        return err
    if cogs < 0:
        return {"ok": False, "error": f"cogs cannot be negative (got {cogs})"}
    if not 1 <= days <= 365:
        return {"ok": False, "error": f"days must be between 1 and 365 (got {days})"}
    fee_data = await sp.get_fee_estimate(asin, sale_price)
    total_fees = fee_data.get("total_fees", 0) or 0
    gross_margin = sale_price - total_fees - cogs
    margin_pct = round(gross_margin / sale_price * 100, 1) if sale_price else None
    return {
        "ok": True,
        "asin": asin.upper(),
        "sale_price": sale_price,
        "cogs": cogs,
        "fees": fee_data.get("fee_breakdown", {}),
        "total_fees": total_fees,
        "gross_margin_usd": round(gross_margin, 2),
        "gross_margin_pct": margin_pct,
        "net_revenue_after_fees": fee_data.get("net_revenue"),
        "dry_run": fee_data.get("dry_run", False),
        "note": "Add advertising cost per unit for true net profit",
    }


HANDLERS = {
    "product_pricing": product_pricing,
    "competitive_offers": competitive_offers,
    "fee_estimate": fee_estimate,
    "profit_analysis": profit_analysis,
}
