"""amazon_listings domain handlers — Listings Items CRUD with preview/confirm gate.

Write operations (update_price, update_quantity, deactivate, delete) require
confirm=True to execute. Without it, they return a preview of the intended change.
This mirrors the inbound plan preview/confirm pattern for safety.
"""
from __future__ import annotations

from typing import Any

from amazon_mcp.tools.deps import ctx_from_params, get_tool_deps


def _preview(action: str, sku: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "preview_only": True,
        "action": action,
        "sku": sku,
        "proposed": proposed,
        "instructions": "Add confirm=True to the same call to apply this change.",
    }


async def get_listing(params: dict[str, Any]) -> dict[str, Any]:
    """GET current listing details for a SKU (price, status, ASIN, offers)."""
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    sku = str(params.get("sku") or "").strip()
    if not sku:
        return {"ok": False, "error": "sku is required"}
    raw = await deps.sp_call(sp.get_listing_item(sku), "get_listing_item")
    return __import__("json").loads(raw)


async def update_price(params: dict[str, Any]) -> dict[str, Any]:
    """Update listing price.

    Preview (default): returns proposed change.
    Confirm (confirm=True): sends PATCH to Listings v2021.
    """
    deps = get_tool_deps()
    sku = str(params.get("sku") or "").strip()
    price = params.get("price")
    currency = str(params.get("currency", "USD") or "USD").upper()
    confirm = bool(params.get("confirm", False))

    if not sku:
        return {"ok": False, "error": "sku is required"}
    if price is None or float(price) <= 0:
        return {"ok": False, "error": "price must be a positive number"}

    proposed = {"sku": sku, "price": float(price), "currency": currency}
    if not confirm:
        return _preview("update_price", sku, proposed)

    _, sp, _ = ctx_from_params(params)
    patches = [{
        "op": "replace",
        "path": "/attributes/purchasable_offer",
        "value": [{
            "marketplace_id": sp.cfg.marketplace_id,
            "currency": currency,
            "our_price": [{"schedule": [{"value_with_tax": float(price)}]}],
        }],
    }]
    raw = await deps.sp_call(sp.patch_listing_item(sku, patches), "patch_listing_item:price")
    result = __import__("json").loads(raw)
    result["action"] = "update_price"
    result["proposed"] = proposed
    return result


async def update_quantity(params: dict[str, Any]) -> dict[str, Any]:
    """Update FBM/MFN listing fulfillable quantity.

    Preview (default): returns proposed change.
    Confirm (confirm=True): sends PATCH to Listings v2021.
    Note: for FBA, quantity is controlled by FBA fulfillment; only for FBM listings.
    """
    deps = get_tool_deps()
    sku = str(params.get("sku") or "").strip()
    quantity = params.get("quantity")
    confirm = bool(params.get("confirm", False))

    if not sku:
        return {"ok": False, "error": "sku is required"}
    if quantity is None or int(quantity) < 0:
        return {"ok": False, "error": "quantity must be a non-negative integer"}

    proposed = {"sku": sku, "quantity": int(quantity)}
    if not confirm:
        return _preview("update_quantity", sku, proposed)

    _, sp, _ = ctx_from_params(params)
    patches = [{
        "op": "replace",
        "path": "/attributes/fulfillment_availability",
        "value": [{
            "fulfillment_channel_code": "DEFAULT",
            "quantity": int(quantity),
        }],
    }]
    raw = await deps.sp_call(sp.patch_listing_item(sku, patches), "patch_listing_item:quantity")
    result = __import__("json").loads(raw)
    result["action"] = "update_quantity"
    result["proposed"] = proposed
    return result


async def deactivate_listing(params: dict[str, Any]) -> dict[str, Any]:
    """Set listing status to INACTIVE (stops showing in search, pauses sales).

    Preview (default): describes the change.
    Confirm (confirm=True): sends PATCH to Listings v2021.
    """
    deps = get_tool_deps()
    sku = str(params.get("sku") or "").strip()
    confirm = bool(params.get("confirm", False))

    if not sku:
        return {"ok": False, "error": "sku is required"}

    proposed = {"sku": sku, "status": "INACTIVE", "effect": "listing hidden from search; sales paused"}
    if not confirm:
        return _preview("deactivate_listing", sku, proposed)

    _, sp, _ = ctx_from_params(params)
    patches = [{"op": "replace", "path": "/attributes/item_condition", "value": [{"value": "INACTIVE"}]}]
    raw = await deps.sp_call(sp.patch_listing_item(sku, patches), "patch_listing_item:deactivate")
    result = __import__("json").loads(raw)
    result["action"] = "deactivate_listing"
    result["proposed"] = proposed
    return result


async def activate_listing(params: dict[str, Any]) -> dict[str, Any]:
    """Set listing status back to ACTIVE/BUYABLE.

    Preview (default): describes the change.
    Confirm (confirm=True): sends PATCH to Listings v2021.
    """
    deps = get_tool_deps()
    sku = str(params.get("sku") or "").strip()
    confirm = bool(params.get("confirm", False))

    if not sku:
        return {"ok": False, "error": "sku is required"}

    proposed = {"sku": sku, "status": "ACTIVE", "effect": "listing becomes visible and buyable"}
    if not confirm:
        return _preview("activate_listing", sku, proposed)

    _, sp, _ = ctx_from_params(params)
    patches = [{"op": "replace", "path": "/attributes/item_condition", "value": [{"value": "NEW"}]}]
    raw = await deps.sp_call(sp.patch_listing_item(sku, patches), "patch_listing_item:activate")
    result = __import__("json").loads(raw)
    result["action"] = "activate_listing"
    result["proposed"] = proposed
    return result


async def delete_listing(params: dict[str, Any]) -> dict[str, Any]:
    """Permanently DELETE a listing item (irreversible — SKU and ASIN association removed).

    Preview (default): warns about the irreversibility.
    Confirm (confirm=True): sends DELETE to Listings v2021.
    """
    deps = get_tool_deps()
    sku = str(params.get("sku") or "").strip()
    confirm = bool(params.get("confirm", False))

    if not sku:
        return {"ok": False, "error": "sku is required"}

    proposed = {
        "sku": sku,
        "effect": "PERMANENT — listing and ASIN association deleted; cannot be undone via API",
        "warning": "Use deactivate_listing instead to temporarily hide the listing.",
    }
    if not confirm:
        return _preview("delete_listing", sku, proposed)

    _, sp, _ = ctx_from_params(params)
    raw = await deps.sp_call(sp.delete_listing_item(sku), "delete_listing_item")
    result = __import__("json").loads(raw)
    result["action"] = "delete_listing"
    result["proposed"] = proposed
    return result


HANDLERS = {
    "get_listing": get_listing,
    "update_price": update_price,
    "update_quantity": update_quantity,
    "deactivate_listing": deactivate_listing,
    "activate_listing": activate_listing,
    "delete_listing": delete_listing,
}
