"""amazon_ads domain handlers."""
from __future__ import annotations

from typing import Any

from amazon_mcp.tools.deps import ctx_from_params, get_tool_deps, tenant_id_from_params
from amazon_mcp.tools.helpers import sp_json


async def profile(_params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, _, ads = ctx_from_params(_params)
    return await sp_json(ads.get_profile_info(), "get_advertising_profile")


async def campaign_list(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, _, ads = ctx_from_params(params)
    state = str(params.get("state", "enabled") or "enabled")
    return await sp_json(ads.list_campaigns(state), "get_campaign_list")


async def keyword_performance(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, _, ads = ctx_from_params(params)
    campaign_id = str(params.get("campaign_id", "") or "")
    days = int(params.get("days", 7))
    return await sp_json(ads.keyword_performance(campaign_id, max(1, min(days, 90))), "keyword_performance")


async def sponsored_metrics(_params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, _, ads = ctx_from_params(_params)
    return await sp_json(ads.sponsored_ads_summary(), "sponsored_ads_metrics")


async def search_term_performance(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, _, ads = ctx_from_params(params)
    days = int(params.get("days", 14))
    return await sp_json(ads.get_search_term_performance(max(1, min(days, 60))), "get_search_term_performance")


async def campaign_performance(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, _, ads = ctx_from_params(params)
    days = int(params.get("days", 7))
    return await sp_json(ads.get_campaign_performance(max(1, min(days, 60))), "get_campaign_performance")


async def product_ad_performance(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, _, ads = ctx_from_params(params)
    days = int(params.get("days", 7))
    return await sp_json(ads.get_product_ad_performance(max(1, min(days, 60))), "get_product_ad_performance")


async def pause_campaign(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, _, ads = ctx_from_params(params)
    campaign_id = str(params.get("campaign_id") or params.get("campaignId") or "").strip()
    return await sp_json(ads.pause_campaign(campaign_id), "pause_campaign")


HANDLERS = {
    "profile": profile,
    "campaign_list": campaign_list,
    "keyword_performance": keyword_performance,
    "sponsored_metrics": sponsored_metrics,
    "search_term_performance": search_term_performance,
    "campaign_performance": campaign_performance,
    "product_ad_performance": product_ad_performance,
    "pause_campaign": pause_campaign,
}
