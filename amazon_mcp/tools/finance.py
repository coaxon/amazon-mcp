"""amazon_finance domain handlers."""
from __future__ import annotations

from typing import Any

from amazon_mcp.tools.deps import ctx_from_params, get_tool_deps, tenant_id_from_params
from amazon_mcp.tools.helpers import sp_json


async def financial_summary(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    days = int(params.get("days", 30))
    return await sp_json(sp.get_financial_events(max(1, min(days, 180))), "get_financial_summary")


async def import_cogs(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    csv_content = str(params.get("csv_content", ""))
    tid = tenant_id_from_params(params)
    store_fn = deps.get_cogs_store
    if not store_fn:
        return {"ok": False, "error": "cogs store not configured"}
    try:
        return store_fn(tid).import_csv(csv_content)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def get_cogs(params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    tid = tenant_id_from_params(params)
    store_fn = deps.get_cogs_store
    if not store_fn:
        return {"ok": False, "error": "cogs store not configured"}
    store = store_fn(tid)
    asin = str(params.get("asin", "") or "")
    if not asin.strip():
        rows = store.list_all()
        return {"ok": True, "count": len(rows), "items": rows}
    val = store.get(asin.strip())
    if val is None:
        return {"ok": False, "error": f"No COGS stored for {asin.strip().upper()}"}
    return {"ok": True, "asin": asin.strip().upper(), "cogs": val}


async def transaction_list(params: dict[str, Any]) -> dict[str, Any]:
    """Itemized transaction list using Finances v2024-06-19 API.

    Returns per-transaction data with fee breakdowns, type, marketplace, ASIN.
    Supersedes financial_summary for per-order analysis.
    """
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    days = int(params.get("days", 30))
    next_token = str(params.get("next_token", "") or "")
    page_size = int(params.get("page_size", 100))
    result = await deps.sp_call(
        sp.get_financial_events_v2(days, next_token=next_token, page_size=page_size),
        "get_financial_events_v2",
    )
    data = __import__("json").loads(result)

    txns = data.get("transactions") or []
    by_type: dict[str, int] = {}
    by_type_amount: dict[str, float] = {}
    for tx in txns:
        t = str(tx.get("transactionType") or "Other")
        by_type[t] = by_type.get(t, 0) + 1
        amt = (tx.get("totalAmount") or {}).get("currencyAmount") or 0
        by_type_amount[t] = by_type_amount.get(t, 0) + float(amt)

    return {
        "ok": data.get("ok", True),
        "dry_run": data.get("dry_run", False),
        "period_days": days,
        "total_transactions": data.get("total_transactions", len(txns)),
        "by_type": by_type,
        "by_type_amount_usd": {k: round(v, 2) for k, v in by_type_amount.items()},
        "transactions": txns,
        "next_token": data.get("nextToken"),
        "api_version": "finances/2024-06-19",
    }


async def fee_breakdown(params: dict[str, Any]) -> dict[str, Any]:
    """Aggregate fee breakdown by fee type across all transactions (v2024).

    Returns per-fee-type totals: ReferralFee, FBAPerUnitFulfillmentFee, SubscriptionFee, etc.
    """
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(params)
    days = int(params.get("days", 30))
    result = await deps.sp_call(
        sp.get_financial_events_v2(days),
        "get_financial_events_v2",
    )
    data = __import__("json").loads(result)

    txns = data.get("transactions") or []
    fee_totals: dict[str, float] = {}
    fee_counts: dict[str, int] = {}
    for tx in txns:
        for fee in tx.get("fees") or []:
            fee_type = str(fee.get("feeType") or "Unknown")
            amt = float((fee.get("feeAmount") or {}).get("currencyAmount") or 0)
            fee_totals[fee_type] = round(fee_totals.get(fee_type, 0) + amt, 2)
            fee_counts[fee_type] = fee_counts.get(fee_type, 0) + 1

    sorted_fees = sorted(fee_totals.items(), key=lambda kv: abs(kv[1]), reverse=True)
    total_fees = round(sum(fee_totals.values()), 2)
    return {
        "ok": data.get("ok", True),
        "dry_run": data.get("dry_run", False),
        "period_days": days,
        "total_fees_usd": total_fees,
        "fee_line_items": [
            {"fee_type": k, "total_usd": v, "transaction_count": fee_counts.get(k, 0)}
            for k, v in sorted_fees
        ],
        "transaction_count": len(txns),
        "api_version": "finances/2024-06-19",
    }


HANDLERS = {
    "financial_summary": financial_summary,
    "import_cogs": import_cogs,
    "get_cogs": get_cogs,
    "transaction_list": transaction_list,
    "fee_breakdown": fee_breakdown,
}
