"""DOMAIN_HANDLERS registry and dispatch for amazon_{domain}(action, ...)."""
from __future__ import annotations

import json
import os
from typing import Any, Awaitable, Callable

from amazon_mcp.pro_edition import has_pro, is_pro_required, pro_required_response
from amazon_mcp.tools.deps import get_tool_deps

HandlerFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

DOMAIN_HANDLERS: dict[str, dict[str, HandlerFn]] = {}

LEGACY_TOOL_ALIASES: dict[str, tuple[str, str]] = {
    "amazon_health": ("system", "health"),
    "get_auth_token_status": ("system", "auth_token"),
    "get_server_metrics": ("system", "metrics"),
    "get_marketplace_participations": ("system", "marketplaces"),
    "get_seller_feedback": ("account", "feedback"),
    "list_notification_subscriptions": ("account", "list_subscriptions"),
    "subscribe_any_offer_changed": ("account", "subscribe_offer_changed"),
    "subscribe_fba_inventory_availability_changes": ("account", "subscribe_inventory_availability"),
    "product_lookup": ("catalog", "lookup"),
    "bulk_product_lookup": ("catalog", "bulk_lookup"),
    "search_products": ("catalog", "search"),
    "get_listing_quality": ("catalog", "listing_quality"),
    "category_competitor_insights": ("catalog", "competitor_insights"),
    "get_product_pricing": ("pricing", "product_pricing"),
    "get_competitive_offers": ("pricing", "competitive_offers"),
    "get_fee_estimate": ("pricing", "fee_estimate"),
    "get_profit_analysis": ("pricing", "profit_analysis"),
    "sales_revenue_summary": ("orders", "revenue_summary"),
    "list_orders": ("orders", "list"),
    "get_order_details": ("orders", "order_details"),
    "get_sales_by_asin": ("orders", "sales_by_asin"),
    "list_orders_next_page": ("orders", "next_page"),
    "inventory_levels": ("inventory", "levels"),
    "list_inventory_asins": ("inventory", "list_asins"),
    "get_inventory_health": ("inventory", "health"),
    "get_stranded_inventory": ("inventory", "stranded"),
    "get_suppressed_listings": ("inventory", "suppressed"),
    "reorder_calculator": ("inventory", "reorder_calculator"),
    "create_sp_report": ("report", "create"),
    "get_report_status": ("report", "status"),
    "download_report": ("report", "download"),
    "get_brand_analytics_report": ("report", "brand_analytics"),
    "get_advertising_profile": ("ads", "profile"),
    "get_campaign_list": ("ads", "campaign_list"),
    "keyword_performance": ("ads", "keyword_performance"),
    "sponsored_ads_metrics": ("ads", "sponsored_metrics"),
    "get_search_term_performance": ("ads", "search_term_performance"),
    "get_campaign_performance": ("ads", "campaign_performance"),
    "get_product_ad_performance": ("ads", "product_ad_performance"),
    "get_financial_summary": ("finance", "financial_summary"),
    "import_cogs": ("finance", "import_cogs"),
    "get_cogs": ("finance", "get_cogs"),
    "create_fba_inbound_plan": ("fulfillment", "create_inbound_plan"),
    "get_fba_inbound_plan": ("fulfillment", "get_inbound_plan"),
    "get_fba_operation_status": ("fulfillment", "operation_status"),
    "get_fba_reimbursement_summary": ("fulfillment", "reimbursement_summary"),
    "get_sales_traffic_analytics": ("analytics", "sales_traffic"),
    "get_data_kiosk_status": ("analytics", "kiosk_status"),
    "run_custom_kiosk_query": ("analytics", "custom_kiosk_query"),
    "configure_inventory_alert": ("alerts", "configure_inventory"),
    "add_price_watch": ("alerts", "add_price_watch"),
    "get_pending_alerts": ("alerts", "pending_alerts"),
    "dismiss_alert": ("alerts", "dismiss"),
    "get_alert_config": ("alerts", "alert_config"),
    "trigger_manual_check": ("alerts", "manual_check"),
    "get_operations_health_report": ("insights", "operations_health"),
    "how_long_inventory_last": ("insights", "inventory_last"),
    "protect_profit_margin": ("insights", "protect_margin"),
    "competitor_price_alert": ("insights", "competitor_price_alert"),
    "get_notification_config": ("notify", "notification_config"),
    "test_notification_channel": ("notify", "test_channel"),
}


def register_domain(domain: str, handlers: dict[str, HandlerFn]) -> None:
    DOMAIN_HANDLERS[domain] = dict(handlers)


def list_domains() -> list[str]:
    return sorted(DOMAIN_HANDLERS.keys())


def list_domain_actions(domain: str) -> list[str]:
    return sorted(DOMAIN_HANDLERS.get(domain, {}).keys())


def _parse_params(params_json: str) -> dict[str, Any]:
    raw = (params_json or "").strip() or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"_error": f"invalid params_json: {exc}"}
    if not isinstance(parsed, dict):
        return {"_error": "params_json must decode to a JSON object"}
    return parsed


async def invoke(domain: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = dict(params or {})
    if params.get("_error"):
        return {"ok": False, "error": params["_error"]}

    if is_pro_required(domain, action):
        if not has_pro():
            return pro_required_response(domain=domain, action=action)
        from amazon_mcp_pro.dispatch import invoke_pro

        return await invoke_pro(domain, action, params)

    handlers = DOMAIN_HANDLERS.get(domain)
    if not handlers:
        return {"ok": False, "error": f"unknown domain: {domain}", "supported_domains": list_domains()}
    handler = handlers.get(action)
    if not handler:
        return {
            "ok": False,
            "error": f"unknown action '{action}' for domain '{domain}'",
            "supported_actions": list_domain_actions(domain),
        }
    try:
        data = await handler(params)
        if not isinstance(data, dict):
            return {"ok": False, "error": "handler must return dict", "domain": domain, "action": action}
        return data
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_type": type(exc).__name__, "domain": domain, "action": action}


async def dispatch_legacy(tool_name: str, params: dict[str, Any] | None = None, tenant_id: str = "default") -> str:
    alias = LEGACY_TOOL_ALIASES.get(tool_name)
    if not alias:
        return get_tool_deps().json_dumps({"ok": False, "error": f"no legacy alias for {tool_name}"})
    domain, action = alias
    merged = dict(params or {})
    merged.setdefault("tenant_id", tenant_id)
    if has_pro():
        from amazon_mcp_pro.dispatch import record_tool_usage_pro

        record_tool_usage_pro(tenant_id, tool_name)
    data = await invoke(domain, action, merged)
    return get_tool_deps().json_dumps(data)


async def dispatch_domain(domain: str, action: str, params="{}", tenant_id: str = "") -> str:
    deps = get_tool_deps()
    if isinstance(params, dict):
        resolved = dict(params)
    else:
        resolved = _parse_params(str(params))
    if not tenant_id:
        tenant_id = resolved.get("tenant_id") or os.environ.get("AMAZON_TENANT_ID", "default")
    resolved["tenant_id"] = tenant_id
    if has_pro():
        from amazon_mcp_pro.dispatch import record_tool_usage_pro

        record_tool_usage_pro(tenant_id, f"{domain}.{action}")
    data = await invoke(domain, action, resolved)
    dry_run = True
    try:
        if deps.ensure_default_tenant:
            deps.ensure_default_tenant()
        cfg, _, _ = deps.ctx(tenant_id)
        dry_run = cfg.dry_run
    except ValueError:
        pass
    envelope = {
        "ok": data.get("ok", "error" not in data and not data.get("pro_required")),
        "domain": f"amazon_{domain}",
        "action": action,
        "data": data,
        "meta": {
            "dry_run": dry_run,
            "edition": "pro" if has_pro() else "core",
            "source": "domain_dispatch",
            "supported_actions": list_domain_actions(domain),
            "tenant_id": tenant_id,
        },
    }
    if data.get("error") and envelope["ok"]:
        envelope["ok"] = False
    return deps.json_dumps(envelope)


def bootstrap_domains() -> None:
    from amazon_mcp.tools import account as account_tools
    from amazon_mcp.tools import ads as ads_tools
    from amazon_mcp.tools import alerts as alerts_tools
    from amazon_mcp.tools import analytics as analytics_tools
    from amazon_mcp.tools import catalog as catalog_tools
    from amazon_mcp.tools import finance as finance_tools
    from amazon_mcp.tools import fulfillment as fulfillment_tools
    from amazon_mcp.tools import inventory as inventory_tools
    from amazon_mcp.tools import listings as listings_tools
    from amazon_mcp.tools import orders as orders_tools
    from amazon_mcp.tools import pricing as pricing_tools
    from amazon_mcp.tools import report as report_tools
    from amazon_mcp.tools import system as system_tools

    register_domain("system", system_tools.HANDLERS)
    register_domain("account", account_tools.HANDLERS)
    register_domain("catalog", catalog_tools.HANDLERS)
    register_domain("pricing", pricing_tools.HANDLERS)
    register_domain("orders", orders_tools.HANDLERS)
    register_domain("inventory", inventory_tools.HANDLERS)
    register_domain("listings", listings_tools.HANDLERS)
    register_domain("report", report_tools.HANDLERS)
    register_domain("ads", ads_tools.HANDLERS)
    register_domain("finance", finance_tools.HANDLERS)
    register_domain("fulfillment", fulfillment_tools.HANDLERS)
    register_domain("analytics", analytics_tools.HANDLERS)
    register_domain("alerts", alerts_tools.HANDLERS)

    if has_pro():
        from amazon_mcp_pro.dispatch import bootstrap_domains_pro

        bootstrap_domains_pro()
