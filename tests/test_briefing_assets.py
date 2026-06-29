"""Briefing chart PNG + PDF generation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.reports.briefing_assets import generate_briefing_assets, resolve_asset_path
from amazon_mcp.reports.sales_trend import fetch_daily_sales_series, render_sales_trend_png
from amazon_mcp.integrations.slack_blocks import build_daily_briefing_blocks
from fixtures.fixture_sp_client import FixtureSPClient


@pytest.fixture
def asset_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAZON_BRIEFING_ASSETS_DIR", str(tmp_path / "assets"))
    monkeypatch.setenv("AMAZON_MCP_PUBLIC_BASE_URL", "https://briefing.example.com")


@pytest.mark.asyncio
async def test_fetch_daily_sales_fixture():
    sp = FixtureSPClient()
    rows = await fetch_daily_sales_series(sp, "B0FIXTURE01")
    assert len(rows) == 7
    assert sum(r["units"] for r in rows) > 0


@pytest.mark.asyncio
async def test_generate_briefing_assets(asset_dir):
    sp = FixtureSPClient()
    briefing = {
        "date": "2026-06-15",
        "summary": "test",
        "scoring_version": "v1-weighted",
        "dry_run": True,
        "fba_reimbursement_check": {"ok": True, "period_days": 30, "total_reimbursed_usd": 33.75, "reimbursement_count": 2, "recent": []},
        "account_health_check": {"ok": True, "account_health_score": 92, "metrics": {"ipi_score": 512}},
        "reorder_alerts": [{"asin": "B0FIXTURE01", "current_inventory": 8, "reorder_point": 336, "suggested_order_qty": 328, "daily_sales_rate": 12, "lead_time_days": 14, "safety_stock_days": 14}],
        "profit_snapshot": {},
    }
    assets = await generate_briefing_assets(briefing, sp, top_n=1)
    assert assets["ok"] is True
    assert Path(assets["chart_path"]).is_file()
    assert Path(assets["pdf_path"]).is_file()
    assert assets["chart_url"].startswith("https://briefing.example.com/briefing/assets/")
    assert resolve_asset_path(assets["token"], "sales_trend.png") is not None


def test_slack_blocks_include_image_and_pdf_button(asset_dir):
    briefing = {
        "date": "2026-06-15",
        "summary": "s",
        "briefing_assets": {
            "ok": True,
            "chart_url": "https://briefing.example.com/briefing/assets/tok/sales_trend.png",
            "pdf_url": "https://briefing.example.com/briefing/assets/tok/briefing_report.pdf",
            "chart_asins": ["B0FIXTURE01"],
        },
        "meta": {},
    }
    blocks = build_daily_briefing_blocks(briefing)
    blob = json.dumps(blocks)
    assert '"type": "image"' in blob or '"type":"image"' in blob.replace(" ", "")
    assert "Download Full Report" in blob
