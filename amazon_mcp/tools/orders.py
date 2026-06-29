"""amazon_orders domain handlers."""
from __future__ import annotations

from typing import Any

from amazon_mcp.tools.deps import ctx_from_params, get_tool_deps, tenant_id_from_params
from amazon_mcp.tools.helpers import sp_json


async def revenue_summary(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    days = int(params.get("days", 7))
    return await sp_json(sp.get_orders_metrics(max(1, min(days, 90))), "sales_revenue_summary")


async def list_orders(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    days = int(params.get("days", 7))
    status = str(params.get("status", "") or "")
    return await sp_json(sp.list_orders(max(1, min(days, 90)), status), "list_orders")


async def order_details(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    order_id = str(params.get("order_id", "")).strip()
    return await sp_json(sp.get_order_details(order_id), "get_order_details")


async def sales_by_asin(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    days = int(params.get("days", 30))
    return await sp_json(sp.get_sales_by_asin(max(1, min(days, 90))), "get_sales_by_asin")


async def next_page(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    next_token = str(params.get("next_token", "")).strip()
    return await sp_json(sp.list_orders_page(next_token), "list_orders_next_page")


HANDLERS = {
    "revenue_summary": revenue_summary,
    "list": list_orders,
    "order_details": order_details,
    "sales_by_asin": sales_by_asin,
    "next_page": next_page,
}
