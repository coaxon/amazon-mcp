"""Tests for aging_inventory and fnsku_reorder — Feature D."""
from __future__ import annotations

import asyncio
import json
import os
import pytest

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")

import amazon_mcp.server as _srv
from amazon_mcp.tools.domain_tools import EXPORTS


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    _srv._reset_ctx_cache()


def _call(coro):
    return json.loads(asyncio.run(coro))


class TestAgingInventory:
    def test_basic_structure(self):
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("aging_inventory"))
        assert raw["ok"] is True
        inner = raw.get("data", raw)
        assert "summary" in inner
        assert "exceeded" in inner
        assert "at_risk" in inner
        assert "safe" in inner
        assert inner["ltsf_threshold_days"] == 181

    def test_fixture_has_exceeded_items(self):
        """Fixture includes B0FIXTURE03 at ~190 days — should appear in exceeded."""
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("aging_inventory"))
        inner = raw.get("data", raw)
        exceeded = inner.get("exceeded", [])
        assert len(exceeded) >= 1, "Expected at least one LTSF-exceeded item from fixture"
        asins = [e["asin"] for e in exceeded]
        assert "B0FIXTURE03" in asins

    def test_fixture_has_at_risk_items(self):
        """Fixture includes B0FIXTURE04 at ~160 days — should appear in at_risk."""
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("aging_inventory"))
        inner = raw.get("data", raw)
        at_risk = inner.get("at_risk", [])
        assert len(at_risk) >= 1, "Expected at least one at-risk item from fixture"
        asins = [e["asin"] for e in at_risk]
        assert "B0FIXTURE04" in asins

    def test_at_risk_items_have_days_until_ltsf(self):
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("aging_inventory"))
        inner = raw.get("data", raw)
        for item in inner.get("at_risk", []):
            assert "days_until_ltsf" in item
            assert item["days_until_ltsf"] >= 0

    def test_exceeded_items_have_action(self):
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("aging_inventory"))
        inner = raw.get("data", raw)
        for item in inner.get("exceeded", []):
            assert "action" in item
            assert item["ltsf_risk"] == "exceeded"

    def test_custom_warn_days(self):
        """Lower warn_days threshold should capture more items."""
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw_default = _call(amazon_inventory("aging_inventory", warn_days=150))
        raw_aggressive = _call(amazon_inventory("aging_inventory", warn_days=30))
        inner_def = raw_default.get("data", raw_default)
        inner_agg = raw_aggressive.get("data", raw_aggressive)
        assert inner_agg["summary"]["at_risk"] >= inner_def["summary"]["at_risk"]

    def test_summary_counts_add_up(self):
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("aging_inventory"))
        inner = raw.get("data", raw)
        s = inner["summary"]
        total = s["exceeded_ltsf"] + s["at_risk"] + s["safe"] + s["unknown_age"]
        assert total == s["total_skus"]

    def test_fnsku_present_in_results(self):
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("aging_inventory"))
        inner = raw.get("data", raw)
        all_items = inner.get("exceeded", []) + inner.get("at_risk", []) + inner.get("safe", [])
        for item in all_items:
            assert "fnsku" in item


class TestFnskuReorder:
    def test_basic_structure(self):
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("fnsku_reorder"))
        assert raw["ok"] is True
        inner = raw.get("data", raw)
        assert "fnsku_count" in inner
        assert "reorder_alerts" in inner
        assert "calculations" in inner

    def test_each_row_has_fnsku(self):
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("fnsku_reorder"))
        inner = raw.get("data", raw)
        for row in inner.get("calculations", []):
            assert "fnsku" in row
            assert "sku" in row

    def test_reorder_alerts_subset_of_calculations(self):
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("fnsku_reorder"))
        inner = raw.get("data", raw)
        alert_count = len(inner.get("reorder_alerts", []))
        total = inner.get("fnsku_count", 0)
        assert alert_count <= total

    def test_custom_lead_time(self):
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("fnsku_reorder", lead_time_days=30))
        inner = raw.get("data", raw)
        assert inner.get("lead_time_days") == 30

    def test_reorder_point_formula(self):
        """below_reorder_point must be consistent with current_inventory vs reorder_point."""
        amazon_inventory = EXPORTS["amazon_inventory"]
        raw = _call(amazon_inventory("fnsku_reorder"))
        inner = raw.get("data", raw)
        for row in inner.get("calculations", []):
            if row.get("ok") and row.get("reorder_point") is not None:
                expected = row["current_inventory"] < row["reorder_point"]
                assert row["below_reorder_point"] == expected


class TestAmazonDaily:
    def test_amazon_daily_returns_briefing(self):
        raw = _call(_srv.amazon_daily())
        data = json.loads(json.dumps(raw)) if isinstance(raw, str) else raw
        if isinstance(data, str):
            data = json.loads(data)
        assert data.get("ok") is True
        assert data.get("scenario") == "daily_briefing"
