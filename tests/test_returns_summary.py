"""FBA returns summary report flow tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.auth.lwa import LWAAuth
from amazon_mcp.clients.rate_limit import RateLimitRegistry
from amazon_mcp.clients.sp_api import SPAPIClient
from amazon_mcp.config import AmazonConfig
from amazon_mcp.scenarios.returns_summary import (
    fetch_returns_summary,
    parse_returns_tsv,
    summarize_returns,
)
from fixtures.loader import fixture_path


@pytest.fixture
def dry_sp(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    cfg = AmazonConfig.from_env()
    return SPAPIClient(cfg, LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token), RateLimitRegistry())


def test_parse_returns_tsv_fixture():
    text = fixture_path("sp_api", "fba_returns.tsv").read_text(encoding="utf-8")
    rows = parse_returns_tsv(text)
    assert len(rows) == 3
    assert sum(r["quantity"] for r in rows) == 4


def test_summarize_returns_with_rate():
    text = fixture_path("sp_api", "fba_returns.tsv").read_text(encoding="utf-8")
    rows = parse_returns_tsv(text)
    summary = summarize_returns(rows, days=30, units_sold=420)
    assert summary["total_quantity_returned"] == 4
    assert summary["total_refund_usd"] == 87.0
    assert summary["return_rate_pct"] == pytest.approx(0.95, abs=0.01)


@pytest.mark.asyncio
async def test_create_returns_report_dry_run(dry_sp):
    created = await dry_sp.create_report("returns", 30)
    assert created["reportType"] == "GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA"
    assert created["reportId"] == "REPORT-DRY-RETURNS"


@pytest.mark.asyncio
async def test_fetch_returns_summary_dry_run(dry_sp):
    summary = await fetch_returns_summary(dry_sp, days=30)
    assert summary["ok"] is True
    assert summary["return_event_count"] == 3
    assert summary["total_quantity_returned"] == 4
    assert summary["dry_run"] is True
    assert summary.get("return_rate_pct") is not None
