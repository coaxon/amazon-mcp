"""amazon_analytics domain handlers (Data Kiosk)."""
from __future__ import annotations

from typing import Any

from amazon_mcp.tools.deps import ctx_from_params, get_tool_deps, tenant_id_from_params
from amazon_mcp.tools.helpers import sp_json


async def sales_traffic(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    days = int(params.get("days", 30))
    granularity = str(params.get("granularity", "DAY") or "DAY")
    return await sp_json(sp.get_sales_traffic_kiosk(max(1, min(days, 365)), granularity), "get_sales_traffic_analytics")


async def kiosk_status(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    query_id = str(params.get("query_id", "")).strip()
    return await sp_json(sp.get_data_kiosk_query_status(query_id), "get_data_kiosk_status")


async def custom_kiosk_query(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    graphql_query = str(params.get("graphql_query", ""))
    return await sp_json(sp.create_data_kiosk_query(graphql_query), "run_custom_kiosk_query")


HANDLERS = {
    "sales_traffic": sales_traffic,
    "kiosk_status": kiosk_status,
    "custom_kiosk_query": custom_kiosk_query,
}
