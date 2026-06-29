"""Ensure seller-facing API strings contain no CJK characters or fullwidth punctuation."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.monitor.alert_store import AlertStore
from amazon_mcp.monitor.thresholds import AlertRecord, InventoryThreshold, PriceWatch
from amazon_mcp.scoring.operations_health import build_operations_health_report
import amazon_mcp.server as srv
from amazon_mcp.server import (
    configure_inventory_alert,
    add_price_watch,
    get_operations_health_report,
    run_scenario,
)

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_FULLWIDTH = re.compile(r"[\uFF00-\uFFEF]")


def _collect_strings(obj, out: list[str]) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_strings(v, out)


def _assert_seller_facing_english(strings: list[str], context: str) -> None:
    cjk_bad = [s for s in strings if _CJK.search(s)]
    assert not cjk_bad, f"CJK in {context}: {cjk_bad[:5]}"
    fw_bad = [s for s in strings if _FULLWIDTH.search(s)]
    assert not fw_bad, f"Fullwidth punctuation in {context}: {fw_bad[:5]}"


def test_operations_health_strings_english():
    asin = "B0HIGHRISK"
    inv = [{"asin": asin, "inventoryDetails": {"fulfillableQuantity": 0}}]
    camp = {"account_totals": {"spend": 100, "sales": 200, "acos": 0.40, "roas": 2.0}, "campaigns": []}
    comp = {asin: {"buy_box_price": 24.0, "offers": [{"price": 30.0, "is_buy_box_winner": True}]}}
    report = build_operations_health_report(asins=[asin], inventory_summaries=inv, campaign_data=camp, competitive_by_asin=comp)
    strings: list[str] = []
    _collect_strings(report, strings)
    _assert_seller_facing_english(strings, "operations_health report")


@pytest.mark.asyncio
async def test_daily_briefing_strings_english(monkeypatch, tmp_path):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    srv._reset_ctx_cache()
    store = AlertStore(str(tmp_path / "cjk.db"))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-FIX-001", "B0FIXTURE01", 20))
    store.add_alert(AlertRecord(alert_type="LOW_INVENTORY", severity="WARN", title="Low stock", asin="B0FIXTURE01"))
    monkeypatch.setattr(srv, "_alert_store", store)
    data = json.loads(await run_scenario("daily_briefing"))
    strings: list[str] = []
    _collect_strings(data, strings)
    _assert_seller_facing_english(strings, "daily_briefing")


@pytest.mark.asyncio
async def test_tool_response_messages_english(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    srv._reset_ctx_cache()
    for raw in [
        await configure_inventory_alert("SKU-X", "B0TEST", 10),
        await add_price_watch("B0TEST", 29.99, 0.05),
        await get_operations_health_report(""),
        await run_scenario("not_a_scenario"),
    ]:
        data = json.loads(raw)
        strings: list[str] = []
        _collect_strings(data, strings)
        _assert_seller_facing_english(strings, f"tool response {data.get('error') or data.get('action')}")
