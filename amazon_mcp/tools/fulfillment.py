"""amazon_fulfillment domain handlers — core inbound plan paths."""
from __future__ import annotations

import json
from typing import Any

from amazon_mcp.tools.deps import ctx_from_params
from amazon_mcp.tools.helpers import sp_json


async def create_inbound_plan(params: dict[str, Any]) -> dict[str, Any]:
    _, sp, _ = ctx_from_params(params)
    items_json = str(params.get("items_json", ""))
    source_address_json = str(params.get("source_address_json", ""))
    plan_name = str(params.get("plan_name", "") or "")
    try:
        items = json.loads(items_json)
        address = json.loads(source_address_json)
    except Exception as exc:
        return {"ok": False, "error": f"Invalid JSON input: {exc}"}
    return await sp_json(sp.create_inbound_plan(items, address, plan_name), "create_fba_inbound_plan")


async def get_inbound_plan(params: dict[str, Any]) -> dict[str, Any]:
    _, sp, _ = ctx_from_params(params)
    inbound_plan_id = str(params.get("inbound_plan_id", "")).strip()
    return await sp_json(sp.get_inbound_plan(inbound_plan_id), "get_fba_inbound_plan")


async def operation_status(params: dict[str, Any]) -> dict[str, Any]:
    _, sp, _ = ctx_from_params(params)
    operation_id = str(params.get("operation_id", "")).strip()
    return await sp_json(sp.get_inbound_operation_status(operation_id), "get_fba_operation_status")


HANDLERS = {
    "create_inbound_plan": create_inbound_plan,
    "get_inbound_plan": get_inbound_plan,
    "operation_status": operation_status,
}
