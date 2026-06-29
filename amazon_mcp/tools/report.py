"""amazon_report domain handlers."""
from __future__ import annotations

from typing import Any

from amazon_mcp.tools.deps import ctx_from_params, get_tool_deps, tenant_id_from_params
from amazon_mcp.tools.helpers import sp_json


async def create(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    report_type = str(params.get("report_type", ""))
    days = int(params.get("days", 7))
    return await sp_json(sp.create_report(report_type, max(1, min(days, 90))), "create_sp_report")


async def status(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, ads = ctx_from_params(params)
    report_id = str(params.get("report_id", ""))
    source = str(params.get("source", "sp") or "sp")
    if source == "ads":
        return await sp_json(ads.get_report_status(report_id), "get_report_status")
    return await sp_json(sp.get_report_status(report_id), "get_report_status")


async def download(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    document_id = str(params.get("document_id", ""))
    return await sp_json(sp.download_report_document(document_id), "download_report")


async def brand_analytics(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    report_type = str(params.get("report_type", "search_performance") or "search_performance")
    period = str(params.get("period", "WEEK") or "WEEK")
    days = int(params.get("days", 7))
    return await sp_json(sp.get_brand_analytics_report(report_type, period, days), "get_brand_analytics_report")


HANDLERS = {
    "create": create,
    "status": status,
    "download": download,
    "brand_analytics": brand_analytics,
}
