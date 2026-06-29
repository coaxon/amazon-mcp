"""amazon_account domain handlers."""
from __future__ import annotations

import json
import os
from typing import Any

from amazon_mcp.tools.deps import ctx_from_params, get_tool_deps, tenant_id_from_params


async def feedback(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    days = int(params.get("days", 90))
    _, sp, _ = ctx_from_params(params)
    raw = await deps.sp_call(sp.get_seller_feedback(max(1, min(days, 365))), "get_seller_feedback")
    return json.loads(raw)


async def list_subscriptions(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    notification_type = str(params.get("notification_type", "ORDER_CHANGE"))
    _, sp, _ = ctx_from_params(params)
    raw = await deps.sp_call(
        sp.list_notification_subscriptions(notification_type),
        "list_notification_subscriptions",
    )
    return json.loads(raw)


def _default_notification_webhook_url(path: str = "/notifications/webhook") -> str:
    url = str(os.environ.get("AMAZON_MCP_NOTIFICATION_WEBHOOK_URL", "")).strip()
    if url:
        return url
    host = os.environ.get("AMAZON_MCP_HOST", "127.0.0.1")
    port = os.environ.get("AMAZON_MCP_PORT", "8780")
    return f"http://{host}:{port}{path}"


async def subscribe_offer_changed(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    url = str(params.get("webhook_url") or _default_notification_webhook_url("/notifications/any-offer-changed")).strip()
    raw = await deps.sp_call(sp.subscribe_any_offer_changed(url), "subscribe_any_offer_changed")
    return json.loads(raw)



async def subscribe_inventory_availability(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    url = str(params.get("webhook_url") or _default_notification_webhook_url()).strip()
    raw = await deps.sp_call(
        sp.subscribe_fba_inventory_availability_changes(url),
        "subscribe_fba_inventory_availability_changes",
    )
    return json.loads(raw)


async def subscribe_listings_status(params: dict[str, Any]) -> dict[str, Any]:
    """Subscribe to LISTINGS_ITEM_STATUS_CHANGE — receive push when listings go active/inactive/suppressed."""
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    url = str(params.get("webhook_url") or _default_notification_webhook_url("/notifications/listings-status")).strip()
    raw = await deps.sp_call(
        sp.subscribe_listings_item_status_change(url),
        "subscribe_listings_item_status_change",
    )
    return json.loads(raw)


async def subscribe_listings_issues(params: dict[str, Any]) -> dict[str, Any]:
    """Subscribe to LISTINGS_ITEM_ISSUES_CHANGE — receive push when listing has new compliance/attribute errors."""
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    url = str(params.get("webhook_url") or _default_notification_webhook_url("/notifications/listings-issues")).strip()
    raw = await deps.sp_call(
        sp.subscribe_listings_item_issues_change(url),
        "subscribe_listings_item_issues_change",
    )
    return json.loads(raw)


async def subscribe_pricing_health(params: dict[str, Any]) -> dict[str, Any]:
    """Subscribe to PRICING_HEALTH — receive push when Buy Box health or pricing eligibility changes."""
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    url = str(params.get("webhook_url") or _default_notification_webhook_url("/notifications/pricing-health")).strip()
    raw = await deps.sp_call(
        sp.subscribe_pricing_health(url),
        "subscribe_pricing_health",
    )
    return json.loads(raw)


async def unsubscribe(params: dict[str, Any]) -> dict[str, Any]:
    """Delete a notification subscription by type + subscription_id."""
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    notification_type = str(params.get("notification_type", "")).strip().upper()
    subscription_id = str(params.get("subscription_id", "")).strip()
    if not notification_type or not subscription_id:
        return {"ok": False, "error": "notification_type and subscription_id are required"}
    raw = await deps.sp_call(
        sp.delete_notification_subscription(notification_type, subscription_id),
        "delete_notification_subscription",
    )
    return json.loads(raw)


async def subscription_status(params: dict[str, Any]) -> dict[str, Any]:
    """List active subscriptions for a given notification_type (default: all common types)."""
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    notification_type = str(params.get("notification_type", "")).strip().upper()

    common_types = [
        "ANY_OFFER_CHANGED",
        "FBA_INVENTORY_AVAILABILITY_CHANGES",
        "LISTINGS_ITEM_STATUS_CHANGE",
        "LISTINGS_ITEM_ISSUES_CHANGE",
        "PRICING_HEALTH",
        "ORDER_CHANGE",
    ]
    types_to_check = [notification_type] if notification_type else common_types

    results = []
    for ntype in types_to_check:
        raw = await deps.sp_call(
            sp.list_notification_subscriptions(ntype),
            f"list_notification_subscriptions:{ntype}",
        )
        info = json.loads(raw)
        subscriptions = info.get("subscriptions") or []
        results.append({
            "notification_type": ntype,
            "active_subscriptions": len(subscriptions),
            "subscriptions": subscriptions,
        })

    return {
        "ok": True,
        "types_checked": len(types_to_check),
        "summary": [
            {"type": r["notification_type"], "count": r["active_subscriptions"]}
            for r in results
        ],
        "detail": results,
    }


HANDLERS = {
    "feedback": feedback,
    "list_subscriptions": list_subscriptions,
    "subscribe_offer_changed": subscribe_offer_changed,
    "subscribe_inventory_availability": subscribe_inventory_availability,
    "subscribe_listings_status": subscribe_listings_status,
    "subscribe_listings_issues": subscribe_listings_issues,
    "subscribe_pricing_health": subscribe_pricing_health,
    "unsubscribe": unsubscribe,
    "subscription_status": subscription_status,
}
