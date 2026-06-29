"""amazon_alerts domain — core read-only handlers."""
from __future__ import annotations

from typing import Any

from amazon_mcp.tools.deps import get_tool_deps, tenant_id_from_params


async def pending_alerts(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    store = deps.get_store(tenant_id_from_params(params)) if deps.get_store else None
    if not store:
        return {"ok": False, "error": "alert store not configured"}
    limit = int(params.get("limit", 20))
    capped = min(limit, 100)
    alerts = store.get_pending_alerts(capped)
    total = store.count_pending()
    return {
        "ok": True,
        "pending_count": len(alerts),
        "total_count": total,
        "has_more": total > len(alerts),
        "alerts": alerts,
    }


async def alert_config(_params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    store = deps.get_store(tenant_id_from_params(_params)) if deps.get_store else None
    if not store:
        return {"ok": False, "error": "alert store not configured"}
    thresholds = store.list_inventory_thresholds()
    watches = store.list_price_watches()
    pending = store.count_pending()
    return {
        "ok": True,
        "edition": "core",
        "pending_alerts": pending,
        "inventory_thresholds": thresholds,
        "price_watches": watches,
        "monitor_status": {
            "engine_running": False,
            "note": "Active polling requires amazon-mcp-pro (AlertEngine)",
        },
    }


HANDLERS = {
    "pending_alerts": pending_alerts,
    "alert_config": alert_config,
}
