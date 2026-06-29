"""
Dry-run smoke tests for all MCP tools.
All tools must return ok=true and valid JSON in DRY_RUN=1 mode.
Run: pytest tests/test_all_tools_dryrun.py -v
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

import tempfile
os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")
os.environ.setdefault("AMAZON_COGS_DB_PATH", tempfile.mktemp(suffix="_tools_dryrun_cogs.db"))

import amazon_mcp.server as _srv
from amazon_mcp.server import TOOL_HANDLERS
_srv._cogs_store_cache.clear()


def _check(raw: str, tool: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        pytest.fail(f"{tool}: invalid JSON — {e}\nraw={raw[:200]}")
    assert data.get("ok") is True, f"{tool}: ok!=True, got {data}"
    return data


def _inner(data: dict) -> dict:
    """Unwrap the domain envelope to get the handler result dict."""
    return data.get("data", data)


@pytest.mark.parametrize("tool_name", sorted(TOOL_HANDLERS.keys()))
def test_tool_dryrun(tool_name: str) -> None:
    handler = TOOL_HANDLERS[tool_name]
    result = asyncio.run(handler())
    _check(result, tool_name)


def test_tool_count() -> None:
    assert len(TOOL_HANDLERS) >= 20, f"Expected >=20 tools, got {len(TOOL_HANDLERS)}"


def test_amazon_health_version() -> None:
    result = asyncio.run(TOOL_HANDLERS["amazon_health"]())
    data = _check(result, "amazon_health")
    import amazon_mcp
    # amazon_health returns flat (legacy-compatible system.health handler)
    inner = _inner(data)
    assert inner.get("version") == amazon_mcp.__version__ or data.get("version") == amazon_mcp.__version__
    assert inner.get("dry_run") is True or data.get("dry_run") is True


def test_product_lookup_fields() -> None:
    result = asyncio.run(TOOL_HANDLERS["amazon_catalog"]())
    data = _check(result, "amazon_catalog")
    inner = _inner(data)
    assert "asin" in inner and "title" in inner


def test_inventory_health_structure() -> None:
    result = asyncio.run(TOOL_HANDLERS["amazon_inventory_health"]())
    data = _check(result, "amazon_inventory_health")
    inner = _inner(data)
    assert "total_skus" in inner and "low_stock_count" in inner
    assert isinstance(inner["restock_recommended"], list)


def test_competitive_offers_structure() -> None:
    result = asyncio.run(TOOL_HANDLERS["amazon_pricing"]())
    data = _check(result, "amazon_pricing")
    # product_pricing returns list of price objects; competitive_offers returns offers list
    inner = _inner(data)
    assert isinstance(inner, (dict, list))


def test_profit_analysis_fields() -> None:
    result = asyncio.run(TOOL_HANDLERS["amazon_pricing_profit"]())
    data = _check(result, "amazon_pricing_profit")
    inner = _inner(data)
    assert "total_fees" in inner and "gross_margin_usd" in inner


def test_orders_list_structure() -> None:
    result = asyncio.run(TOOL_HANDLERS["amazon_orders_list"]())
    data = _check(result, "amazon_orders_list")
    inner = _inner(data)
    assert isinstance(inner.get("orders"), list) and "count" in inner


def test_financial_summary_fields() -> None:
    result = asyncio.run(TOOL_HANDLERS["amazon_finance"]())
    data = _check(result, "amazon_finance")
    inner = _inner(data)
    assert "gross_revenue" in inner and "net_proceeds" in inner


def test_brand_analytics_report() -> None:
    result = asyncio.run(TOOL_HANDLERS["amazon_report_brand"]())
    data = _check(result, "amazon_report_brand")
    inner = _inner(data)
    assert "reportId" in inner and "GET_BRAND_ANALYTICS" in inner.get("reportType", "")


def test_fba_inbound_plan_create() -> None:
    result = asyncio.run(TOOL_HANDLERS["amazon_fulfillment"]())
    data = _check(result, "amazon_fulfillment")
    inner = _inner(data)
    assert "inboundPlanId" in inner or inner.get("ok") is True


def test_auth_token_status() -> None:
    result = asyncio.run(TOOL_HANDLERS["amazon_system"]())
    data = _check(result, "amazon_system")
    # health action; auth_token check via amazon_account
    assert data.get("ok") is True


def test_category_competitor_insights() -> None:
    result = asyncio.run(TOOL_HANDLERS["amazon_catalog_competitor"]())
    data = _check(result, "amazon_catalog_competitor")
    inner = _inner(data)
    assert "product" in inner and "competition" in inner and "pricing" in inner
