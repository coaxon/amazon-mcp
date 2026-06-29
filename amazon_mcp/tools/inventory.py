"""amazon_inventory domain handlers — core read paths."""
from __future__ import annotations

from typing import Any

from amazon_mcp.refiner.dom_refiner import refine_inventory
from amazon_mcp.tools.deps import ctx_from_params, get_tool_deps
from amazon_mcp.tools.helpers import sp_json


async def levels(params: dict[str, Any]) -> dict[str, Any]:
    _, sp, _ = ctx_from_params(params)
    skus = str(params.get("skus", "") or "")
    sku_list = [s.strip() for s in skus.split(",") if s.strip()] if skus else None
    raw = await sp.get_inventory_summaries(sku_list)
    return refine_inventory(raw)


async def list_asins(_params: dict[str, Any]) -> dict[str, Any]:
    _, sp, _ = ctx_from_params(_params)
    return await sp_json(sp.list_inventory_asins(), "list_inventory_asins")


async def health(_params: dict[str, Any]) -> dict[str, Any]:
    _, sp, _ = ctx_from_params(_params)
    return await sp_json(sp.get_inventory_health(), "get_inventory_health")


async def stranded(_params: dict[str, Any]) -> dict[str, Any]:
    _, sp, _ = ctx_from_params(_params)
    return await sp_json(sp.get_stranded_inventory_report(), "get_stranded_inventory")


async def suppressed(_params: dict[str, Any]) -> dict[str, Any]:
    _, sp, _ = ctx_from_params(_params)
    return await sp_json(sp.get_suppressed_listings_report(), "get_suppressed_listings")


HANDLERS = {
    "levels": levels,
    "list_asins": list_asins,
    "health": health,
    "stranded": stranded,
    "suppressed": suppressed,
}
