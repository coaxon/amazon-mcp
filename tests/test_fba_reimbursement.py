"""FBA reimbursement report flow tests."""
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

from amazon_mcp.clients.sp_api import SPAPIClient
from amazon_mcp.config import AmazonConfig
from amazon_mcp.auth.lwa import LWAAuth
from amazon_mcp.clients.rate_limit import RateLimitRegistry
from amazon_mcp.scenarios.fba_reimbursement import (
    fetch_fba_reimbursement_summary,
    parse_reimbursement_tsv,
    summarize_reimbursements,
)
from fixtures.loader import fixture_path


@pytest.fixture
def dry_sp(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    cfg = AmazonConfig.from_env()
    auth = LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token)
    return SPAPIClient(cfg, auth, RateLimitRegistry())


def test_parse_reimbursement_fixture_tsv():
    text = fixture_path("sp_api", "fba_reimbursements.tsv").read_text(encoding="utf-8")
    rows = parse_reimbursement_tsv(text)
    assert len(rows) == 2
    assert rows[0]["asin"] == "B0FIXTURE01"


def test_summarize_reimbursements_totals():
    text = fixture_path("sp_api", "fba_reimbursements.tsv").read_text(encoding="utf-8")
    summary = summarize_reimbursements(parse_reimbursement_tsv(text), days=30)
    assert summary["reimbursement_count"] == 2
    assert summary["total_reimbursed_usd"] == pytest.approx(33.75, abs=0.01)
    assert summary["by_asin"]["B0FIXTURE01"] == 25.0


@pytest.mark.asyncio
async def test_create_sp_report_reimbursements_dry_run(dry_sp):
    created = await dry_sp.create_report("reimbursements", 30)
    assert created["reportId"] == "REPORT-DRY-REIMB"
    assert created["reportType"] == "GET_FBA_REIMBURSEMENTS_DATA"


@pytest.mark.asyncio
async def test_fetch_fba_reimbursement_summary_dry_run(dry_sp):
    summary = await fetch_fba_reimbursement_summary(dry_sp, days=30)
    assert summary["ok"] is True
    assert summary["reimbursement_count"] == 2
    assert summary["dry_run"] is True
