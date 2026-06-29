"""Tests for C-remaining: Finances v2024 + Brand Analytics item_comparison/alternate_purchase."""
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


def _inner(raw: dict) -> dict:
    return raw.get("data", raw)


# ── Finances v2024 — transaction_list ────────────────────────────────────────

class TestTransactionList:
    def test_returns_ok(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("transaction_list"))
        assert raw["ok"] is True

    def test_has_transactions(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("transaction_list"))
        inner = _inner(raw)
        assert "transactions" in inner
        assert inner.get("total_transactions", 0) >= 1

    def test_api_version_v2024(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("transaction_list"))
        inner = _inner(raw)
        assert "2024" in str(inner.get("api_version", ""))

    def test_by_type_summary(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("transaction_list"))
        inner = _inner(raw)
        assert "by_type" in inner
        assert len(inner["by_type"]) >= 1

    def test_by_type_amount_present(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("transaction_list"))
        inner = _inner(raw)
        assert "by_type_amount_usd" in inner

    def test_each_transaction_has_type(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("transaction_list"))
        inner = _inner(raw)
        for tx in inner.get("transactions", []):
            assert "transactionType" in tx

    def test_each_transaction_has_posted_date(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("transaction_list"))
        inner = _inner(raw)
        for tx in inner.get("transactions", []):
            assert "postedDate" in tx

    def test_each_transaction_has_fees(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("transaction_list"))
        inner = _inner(raw)
        order_txns = [tx for tx in inner.get("transactions", []) if tx.get("transactionType") == "Order"]
        for tx in order_txns:
            assert "fees" in tx

    def test_custom_days(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("transaction_list", days=7))
        inner = _inner(raw)
        assert inner.get("period_days") == 7


# ── Finances v2024 — fee_breakdown ───────────────────────────────────────────

class TestFeeBreakdown:
    def test_returns_ok(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("fee_breakdown"))
        assert raw["ok"] is True

    def test_has_fee_line_items(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("fee_breakdown"))
        inner = _inner(raw)
        assert "fee_line_items" in inner
        assert len(inner["fee_line_items"]) >= 1

    def test_each_line_item_has_required_fields(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("fee_breakdown"))
        inner = _inner(raw)
        for item in inner.get("fee_line_items", []):
            assert "fee_type" in item
            assert "total_usd" in item
            assert "transaction_count" in item

    def test_total_fees_is_sum_of_line_items(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("fee_breakdown"))
        inner = _inner(raw)
        expected = round(sum(item["total_usd"] for item in inner.get("fee_line_items", [])), 2)
        actual = round(inner.get("total_fees_usd", 0), 2)
        assert abs(expected - actual) < 0.02  # float rounding tolerance

    def test_api_version_v2024(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("fee_breakdown"))
        inner = _inner(raw)
        assert "2024" in str(inner.get("api_version", ""))

    def test_referral_fee_present_in_dry_run(self):
        amazon_finance = EXPORTS["amazon_finance"]
        raw = _call(amazon_finance("fee_breakdown"))
        inner = _inner(raw)
        fee_types = [item["fee_type"] for item in inner.get("fee_line_items", [])]
        assert "ReferralFee" in fee_types


# ── Brand Analytics — item_comparison ────────────────────────────────────────

class TestBrandAnalyticsItemComparison:
    def test_returns_ok(self):
        amazon_report = EXPORTS["amazon_report"]
        raw = _call(amazon_report("brand_analytics", report_type="item_comparison"))
        assert raw["ok"] is True

    def test_report_type_is_item_comparison(self):
        amazon_report = EXPORTS["amazon_report"]
        raw = _call(amazon_report("brand_analytics", report_type="item_comparison"))
        inner = _inner(raw)
        assert "ITEM_COMPARISON" in str(inner.get("reportType", "")).upper()

    def test_dry_run_has_preview(self):
        amazon_report = EXPORTS["amazon_report"]
        raw = _call(amazon_report("brand_analytics", report_type="item_comparison"))
        inner = _inner(raw)
        preview = inner.get("preview") or {}
        assert "asin" in preview
        assert "comparedAsin" in preview

    def test_view_share_pct_present(self):
        amazon_report = EXPORTS["amazon_report"]
        raw = _call(amazon_report("brand_analytics", report_type="item_comparison"))
        inner = _inner(raw)
        preview = inner.get("preview") or {}
        assert "viewSharePct" in preview


# ── Brand Analytics — alternate_purchase ─────────────────────────────────────

class TestBrandAnalyticsAlternatePurchase:
    def test_returns_ok(self):
        amazon_report = EXPORTS["amazon_report"]
        raw = _call(amazon_report("brand_analytics", report_type="alternate_purchase"))
        assert raw["ok"] is True

    def test_report_type_is_alternate_purchase(self):
        amazon_report = EXPORTS["amazon_report"]
        raw = _call(amazon_report("brand_analytics", report_type="alternate_purchase"))
        inner = _inner(raw)
        assert "ALTERNATE_PURCHASE" in str(inner.get("reportType", "")).upper()

    def test_dry_run_has_preview(self):
        amazon_report = EXPORTS["amazon_report"]
        raw = _call(amazon_report("brand_analytics", report_type="alternate_purchase"))
        inner = _inner(raw)
        preview = inner.get("preview") or {}
        assert "alternatePurchaseAsin" in preview
        assert "alternatePurchaseCount" in preview

    def test_all_six_brand_analytics_types(self):
        """All 6 brand analytics report types must return ok."""
        amazon_report = EXPORTS["amazon_report"]
        for report_type in [
            "search_performance",
            "market_basket",
            "repeat_purchase",
            "demographics",
            "item_comparison",
            "alternate_purchase",
        ]:
            raw = _call(amazon_report("brand_analytics", report_type=report_type))
            assert raw["ok"] is True, f"brand_analytics report_type={report_type} returned ok=False"
