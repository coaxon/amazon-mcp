"""Account health v2 — IPI planning + storage fees."""
from __future__ import annotations

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
from amazon_mcp.scenarios.account_health import (
    IPI_SOURCE_PLANNING,
    fetch_account_health_summary,
    parse_inventory_planning_tsv,
    parse_seller_performance_tsv,
    parse_storage_fees_tsv,
    score_account_health,
)
from amazon_mcp.scenarios.cross_domain_rules import build_rule_context, evaluate_cross_domain_rules
from amazon_mcp.scoring.operations_health import build_operations_health_report, SCORING_VERSION_V2
from fixtures.loader import fixture_path


@pytest.fixture
def dry_sp(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    cfg = AmazonConfig.from_env()
    auth = LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token)
    return SPAPIClient(cfg, auth, RateLimitRegistry())


def test_parse_inventory_planning_fixture():
    text = fixture_path("sp_api", "fba_inventory_planning.tsv").read_text(encoding="utf-8")
    parsed = parse_inventory_planning_tsv(text)
    assert parsed["ipi_score"] == 380
    assert parsed["sku_rows"] >= 2


def test_parse_storage_fees_fixture():
    text = fixture_path("sp_api", "fba_storage_fees.tsv").read_text(encoding="utf-8")
    parsed = parse_storage_fees_tsv(text)
    assert parsed["total_usd"] == pytest.approx(45.75)
    assert parsed["by_asin"]["B0FIXTURE01"] == 28.50


@pytest.mark.asyncio
async def test_fetch_account_health_v2_dry_run(dry_sp):
    summary = await fetch_account_health_summary(dry_sp, days=30, revenue_usd=4480.0)
    assert summary["ok"] is True
    assert summary["ipi_source"] == IPI_SOURCE_PLANNING
    assert summary["metrics"]["ipi_score"] == 380
    assert summary["storage_fees"]["total_usd"] == pytest.approx(45.75)
    assert summary["storage_fee_pct_of_revenue"] == pytest.approx(1.02, abs=0.05)
    assert "GET_FBA_INVENTORY_PLANNING_DATA" in summary["data_sources"]


def test_markdown_overstock_rule_uses_planning_ipi_and_storage():
    account = {
        "ok": True,
        "ipi_source": IPI_SOURCE_PLANNING,
        "ipi_source_label": "FBA inventory planning report (real)",
        "metrics": {"ipi_score": 380},
        "storage_fees": {"total_usd": 45.75},
        "storage_fee_pct_of_revenue": 1.02,
    }
    ctx = build_rule_context(
        ad_health={"status": "healthy", "acos": 0.18, "score": 80},
        profit_snapshot={"net_margin_pct": 5.0, "total_revenue": 4480.0},
        account_health_check=account,
        reorder_alerts=[],
        replenishment_recommendations=[{"asin": "B0X", "days_of_cover": 45, "urgency": "LOW"}],
    )
    actions = evaluate_cross_domain_rules(ctx)
    hit = [a for a in actions if a["rule_id"] == "markdown_overstock_low_ipi"]
    assert len(hit) == 1
    assert "380" in hit[0]["reason"]
    assert "45.75" in hit[0]["reason"]
    assert "inventory_planning" in hit[0]["reason"].lower() or "FBA" in hit[0]["reason"]


def test_markdown_rule_skips_estimated_ipi_only():
    account = {
        "ok": True,
        "ipi_source": "seller_performance",
        "metrics": {"ipi_score": 350},
        "storage_fees": {"total_usd": 10.0},
    }
    ctx = build_rule_context(
        ad_health={"status": "healthy", "acos": 0.18, "score": 80},
        profit_snapshot={"total_revenue": 1000.0},
        account_health_check=account,
        reorder_alerts=[],
        replenishment_recommendations=[{"days_of_cover": 45}],
    )
    actions = evaluate_cross_domain_rules(ctx)
    assert not any(a["rule_id"] == "markdown_overstock_low_ipi" for a in actions)


def test_parse_seller_performance_fixture():
    text = fixture_path("sp_api", "seller_performance.tsv").read_text(encoding="utf-8")
    metrics = parse_seller_performance_tsv(text)
    assert metrics["order_defect_rate"] == pytest.approx(0.004, abs=0.0001)
    assert metrics["ipi_score"] == 512


def test_score_account_health_high():
    score = score_account_health({"order_defect_rate": 0.004, "ipi_score": 512, "late_shipment_rate": 0.018})
    assert score >= 80


@pytest.mark.asyncio
async def test_fetch_account_health_dry_run(dry_sp):
    summary = await fetch_account_health_summary(dry_sp, days=30)
    assert summary["ok"] is True
    assert summary["dry_run"] is True


def test_operations_health_v2_fourth_dimension():
    text = fixture_path("sp_api", "seller_performance.tsv").read_text(encoding="utf-8")
    account = {"ok": True, "account_health_score": score_account_health(parse_seller_performance_tsv(text))}
    report = build_operations_health_report(
        asins=["B0FIXTURE01"],
        inventory_summaries=[{"asin": "B0FIXTURE01", "inventoryDetails": {"fulfillableQuantity": 50}}],
        campaign_data={"account_totals": {"spend": 100, "sales": 500, "acos": 0.2}},
        competitive_by_asin={"B0FIXTURE01": {"buy_box_price": 29.99, "offers": [{"price": 29.99, "is_buy_box_winner": True}]}},
        account_health=account,
    )
    assert report["scoring_version"] == SCORING_VERSION_V2
    assert "account_health" in report["health_scores"]
