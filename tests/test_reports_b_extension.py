"""Tests for Feature B extension: multi-ASIN charts + PDF embedded images + aging section."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.reports.briefing_assets import (
    generate_briefing_assets,
    _pick_chart_asins,
    resolve_asset_path,
    MULTI_CHART_FILE,
    AGING_CHART_FILE,
)
from amazon_mcp.reports.sales_trend import (
    render_multi_panel_png,
    render_aging_bar_png,
)
from amazon_mcp.reports.briefing_pdf import render_briefing_pdf
from fixtures.fixture_sp_client import FixtureSPClient


@pytest.fixture
def asset_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAZON_BRIEFING_ASSETS_DIR", str(tmp_path / "assets"))
    monkeypatch.setenv("AMAZON_MCP_PUBLIC_BASE_URL", "https://briefing.example.com")


def _base_briefing() -> dict:
    return {
        "date": "2026-06-26",
        "summary": "3 ASINs below ROP; account healthy",
        "scoring_version": "v1-weighted",
        "dry_run": True,
        "fba_reimbursement_check": {"ok": True, "period_days": 30, "total_reimbursed_usd": 55.50, "reimbursement_count": 3, "recent": []},
        "account_health_check": {"ok": True, "account_health_score": 95, "metrics": {"ipi_score": 530, "order_defect_rate": 0.001, "late_shipment_rate": 0.003}},
        "reorder_alerts": [
            {"asin": "B0FIXTURE01", "current_inventory": 8, "reorder_point": 200, "suggested_order_qty": 192, "daily_sales_rate": 10},
            {"asin": "B0FIXTURE02", "current_inventory": 5, "reorder_point": 150, "suggested_order_qty": 145, "daily_sales_rate": 7},
        ],
        "profit_snapshot": {
            "total_revenue": 12450.0,
            "margin_pct": 22.5,
            "margin_type": "estimated_excludes_cogs",
            "by_asin": {
                "B0FIXTURE01": {"revenue": 7800.0, "referral_fee": 1170.0, "fba_fee": 540.0, "ad_spend": 420.0, "units": 260, "margin_pct": 23.2},
                "B0FIXTURE02": {"revenue": 3200.0, "referral_fee": 480.0, "fba_fee": 280.0, "ad_spend": 160.0, "units": 160, "margin_pct": 20.1},
                "B0FIXTURE03": {"revenue": 1450.0, "referral_fee": 217.0, "fba_fee": 145.0, "ad_spend": 70.0, "units": 58, "margin_pct": 18.0},
            },
        },
        "wow_narrative": {
            "ok": True,
            "wow_change_pct": -5.2,
            "anomaly": False,
            "narrative": "Sales vs last week -5.2% (477 vs 503 units); largest unit drop on B0FIXTURE01",
            "driver_asin": "B0FIXTURE01",
            "by_asin": {
                "B0FIXTURE01": {"current_units": 260, "prior_units": 280, "wow_change_pct": -7.1, "direction": "down"},
                "B0FIXTURE02": {"current_units": 160, "prior_units": 155, "wow_change_pct": 3.2, "direction": "up"},
            },
        },
    }


# ── _pick_chart_asins ─────────────────────────────────────────────────────────

class TestPickChartAsins:
    def test_picks_by_revenue(self):
        briefing = _base_briefing()
        asins = _pick_chart_asins(briefing, limit=3)
        assert asins[0] == "B0FIXTURE01"  # highest revenue

    def test_respects_limit(self):
        briefing = _base_briefing()
        asins = _pick_chart_asins(briefing, limit=2)
        assert len(asins) <= 2

    def test_falls_back_to_reorder_alerts(self):
        briefing = _base_briefing()
        briefing["profit_snapshot"] = {}
        asins = _pick_chart_asins(briefing, limit=3)
        assert "B0FIXTURE01" in asins

    def test_default_limit_3(self):
        briefing = _base_briefing()
        asins = _pick_chart_asins(briefing)
        assert len(asins) <= 3


# ── render_multi_panel_png ────────────────────────────────────────────────────

class TestRenderMultiPanelPng:
    def test_creates_png_no_revenue(self, tmp_path):
        series = {"B0FIX1": [{"date": f"2026-06-{18+i:02d}", "units": 10+i} for i in range(7)]}
        out = tmp_path / "multi.png"
        render_multi_panel_png(series, out)
        assert out.is_file()
        assert out.stat().st_size > 1000

    def test_creates_png_with_revenue(self, tmp_path):
        series = {
            "B0FIX1": [{"date": f"2026-06-{18+i:02d}", "units": 10+i} for i in range(7)],
            "B0FIX2": [{"date": f"2026-06-{18+i:02d}", "units": 5+i} for i in range(7)],
        }
        out = tmp_path / "multi_rev.png"
        render_multi_panel_png(series, out, revenue_by_asin={"B0FIX1": 7800.0, "B0FIX2": 3200.0})
        assert out.is_file()
        size = out.stat().st_size
        assert size > 5000  # 2-panel chart should be larger

    def test_prior_week_dashed(self, tmp_path):
        series = {"B0FIX1": [{"date": f"2026-06-{18+i:02d}", "units": 12+i} for i in range(7)]}
        prior = {"B0FIX1": [{"date": f"2026-06-{11+i:02d}", "units": 10+i} for i in range(7)]}
        out = tmp_path / "multi_wow.png"
        render_multi_panel_png(series, out, prior_series_by_asin=prior)
        assert out.is_file()

    def test_empty_series_doesnt_crash(self, tmp_path):
        out = tmp_path / "empty.png"
        render_multi_panel_png({}, out)
        assert out.is_file()


# ── render_aging_bar_png ──────────────────────────────────────────────────────

class TestRenderAgingBarPng:
    def _exceeded(self):
        return [{"sku": "SKU-003", "asin": "B0FIX003", "estimated_age_days": 192, "ltsf_risk": "exceeded"}]

    def _at_risk(self):
        return [{"sku": "SKU-004", "asin": "B0FIX004", "estimated_age_days": 165, "ltsf_risk": "warning"}]

    def test_creates_png_with_items(self, tmp_path):
        out = tmp_path / "aging.png"
        render_aging_bar_png(self._exceeded(), self._at_risk(), out)
        assert out.is_file()
        assert out.stat().st_size > 2000

    def test_empty_items_creates_placeholder(self, tmp_path):
        out = tmp_path / "aging_empty.png"
        render_aging_bar_png([], [], out)
        assert out.is_file()


# ── render_briefing_pdf with embedded charts ──────────────────────────────────

class TestBriefingPdfEmbedded:
    def test_pdf_with_chart_embedded(self, tmp_path):
        from amazon_mcp.reports.sales_trend import render_sales_trend_png
        chart_path = tmp_path / "trend.png"
        series = {"B0FIX1": [{"date": f"2026-06-{18+i:02d}", "units": 10+i} for i in range(7)]}
        render_sales_trend_png(series, chart_path)
        pdf_path = tmp_path / "briefing.pdf"
        render_briefing_pdf(_base_briefing(), pdf_path, chart_paths=[chart_path])
        assert pdf_path.is_file()
        assert pdf_path.stat().st_size > 5000

    def test_pdf_with_aging_section(self, tmp_path):
        briefing = _base_briefing()
        briefing["aging_inventory"] = {
            "ok": True,
            "ltsf_threshold_days": 181,
            "exceeded": [{"sku": "SKU-003", "asin": "B0FIX003", "fnsku": "X003", "estimated_age_days": 195, "ltsf_risk": "exceeded", "fulfillable_qty": 120}],
            "at_risk": [{"sku": "SKU-004", "asin": "B0FIX004", "fnsku": "X004", "estimated_age_days": 162, "ltsf_risk": "warning", "fulfillable_qty": 30, "days_until_ltsf": 19}],
            "safe": [],
            "summary": {"total_skus": 2, "exceeded_ltsf": 1, "at_risk": 1, "safe": 0, "unknown_age": 0},
        }
        pdf_path = tmp_path / "briefing_aging.pdf"
        render_briefing_pdf(briefing, pdf_path)
        assert pdf_path.is_file()
        assert pdf_path.stat().st_size > 2000

    def test_pdf_with_wow_narrative(self, tmp_path):
        briefing = _base_briefing()
        pdf_path = tmp_path / "briefing_wow.pdf"
        render_briefing_pdf(briefing, pdf_path)
        assert pdf_path.is_file()
        assert pdf_path.stat().st_size > 2000

    def test_pdf_with_profit_snapshot(self, tmp_path):
        briefing = _base_briefing()
        pdf_path = tmp_path / "briefing_profit.pdf"
        render_briefing_pdf(briefing, pdf_path)
        assert pdf_path.is_file()

    def test_missing_chart_doesnt_crash(self, tmp_path):
        pdf_path = tmp_path / "briefing_nochart.pdf"
        render_briefing_pdf(_base_briefing(), pdf_path, chart_paths=["/nonexistent/chart.png"])
        assert pdf_path.is_file()


# ── full integration: generate_briefing_assets top_n=3 ───────────────────────

class TestGenerateBriefingAssetsTopN3:
    @pytest.mark.asyncio
    async def test_generates_multi_chart(self, asset_dir, tmp_path):
        sp = FixtureSPClient()
        assets = await generate_briefing_assets(_base_briefing(), sp, top_n=3)
        assert assets["ok"] is True
        assert Path(assets["chart_path"]).is_file()
        assert Path(assets["multi_chart_path"]).is_file()
        assert Path(assets["pdf_path"]).is_file()

    @pytest.mark.asyncio
    async def test_multi_chart_url_present(self, asset_dir):
        sp = FixtureSPClient()
        assets = await generate_briefing_assets(_base_briefing(), sp, top_n=2)
        assert "multi_chart_url" in assets
        assert assets["multi_chart_url"].startswith("https://briefing.example.com/briefing/assets/")

    @pytest.mark.asyncio
    async def test_aging_chart_generated_when_data_present(self, asset_dir):
        sp = FixtureSPClient()
        briefing = _base_briefing()
        briefing["aging_inventory"] = {
            "exceeded": [{"sku": "SKU-003", "asin": "B0FIX003", "estimated_age_days": 195, "ltsf_risk": "exceeded"}],
            "at_risk": [],
        }
        assets = await generate_briefing_assets(briefing, sp, top_n=1)
        assert "aging_chart_url" in assets
        assert Path(assets["aging_chart_path"]).is_file()

    @pytest.mark.asyncio
    async def test_no_aging_chart_when_no_data(self, asset_dir):
        sp = FixtureSPClient()
        assets = await generate_briefing_assets(_base_briefing(), sp, top_n=1)
        assert "aging_chart_url" not in assets

    @pytest.mark.asyncio
    async def test_chart_asins_up_to_top_n(self, asset_dir):
        sp = FixtureSPClient()
        assets = await generate_briefing_assets(_base_briefing(), sp, top_n=3)
        assert 1 <= len(assets["chart_asins"]) <= 3

    @pytest.mark.asyncio
    async def test_resolve_asset_path_multi_chart(self, asset_dir):
        sp = FixtureSPClient()
        assets = await generate_briefing_assets(_base_briefing(), sp, top_n=2)
        assert resolve_asset_path(assets["token"], MULTI_CHART_FILE) is not None
