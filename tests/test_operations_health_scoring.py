"""Operations health weighted scoring — high/medium/low scenarios."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.scoring.operations_health import (
    build_operations_health_report,
    score_ad_efficiency,
    score_inventory_risk,
    score_price_competitiveness,
    compute_overall,
    SCORING_VERSION_V2,
)
import amazon_mcp.server as srv
from amazon_mcp.server import get_operations_health_report


@pytest.fixture
def dry_run_env(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    srv._reset_ctx_cache()


def _inv_summary(asin: str, qty: int) -> dict:
    return {
        "asin": asin,
        "sellerSku": f"SKU-{asin}",
        "inventoryDetails": {"fulfillableQuantity": qty},
    }


def _competitive(asin: str, your_price: float, buy_box: float, offers: int = 3) -> dict:
    return {
        "asin": asin,
        "buy_box_price": buy_box,
        "offer_count": offers,
        "offers": [{
            "seller": "A1",
            "price": your_price,
            "is_buy_box_winner": True,
        }],
    }


def _campaigns(acos: float, roas: float = 4.0, spend: float = 100, sales: float = None) -> dict:
    if sales is None:
        sales = spend / acos if acos else 0
    return {
        "campaigns": [{"id": "C1", "spend": spend, "sales": sales, "acos": acos}],
        "account_totals": {"spend": spend, "sales": sales, "acos": acos, "roas": roas},
    }


def test_high_risk_scenario():
    asin = "B0HIGHRISK"
    inv_score, urgent = score_inventory_risk([_inv_summary(asin, 0)], [asin])
    ad_score = score_ad_efficiency(_campaigns(0.40, roas=2.0))
    price_score = score_price_competitiveness(asin, _competitive(asin, 30.0, 24.0))
    overall = compute_overall(inv_score, ad_score, price_score)

    report = build_operations_health_report(
        asins=[asin],
        inventory_summaries=[_inv_summary(asin, 0)],
        campaign_data=_campaigns(0.40, roas=2.0),
        competitive_by_asin={asin: _competitive(asin, 30.0, 24.0)},
    )

    assert inv_score <= 15
    assert ad_score <= 45
    assert price_score <= 40
    assert overall <= 35
    assert urgent
    assert any("restock" in r.lower() for r in report["recommendations"])
    assert report["scoring_version"] == "v1-weighted"


def test_medium_risk_scenario():
    asin = "B0MEDIUM"
    inv_score, _ = score_inventory_risk([_inv_summary(asin, 15)], [asin])
    ad_score = score_ad_efficiency(_campaigns(0.22, roas=4.5))
    price_score = score_price_competitiveness(asin, _competitive(asin, 31.0, 29.5))

    report = build_operations_health_report(
        asins=[asin],
        inventory_summaries=[_inv_summary(asin, 15)],
        campaign_data=_campaigns(0.22, roas=4.5),
        competitive_by_asin={asin: _competitive(asin, 31.0, 29.5)},
    )

    assert 50 <= inv_score <= 70
    assert 55 <= ad_score <= 70
    assert 55 <= price_score <= 70
    assert 50 <= report["overall_score"] <= 70
    assert len(report["recommendations"]) >= 1


def test_low_risk_scenario():
    asin = "B0HEALTHY"
    inv_score, urgent = score_inventory_risk([_inv_summary(asin, 60)], [asin])
    ad_score = score_ad_efficiency(_campaigns(0.10, roas=7.0))
    price_score = score_price_competitiveness(asin, _competitive(asin, 28.99, 28.99))

    report = build_operations_health_report(
        asins=[asin],
        inventory_summaries=[_inv_summary(asin, 60)],
        campaign_data=_campaigns(0.10, roas=7.0),
        competitive_by_asin={asin: _competitive(asin, 28.99, 28.99)},
    )

    assert inv_score >= 80
    assert ad_score >= 90
    assert price_score >= 90
    assert report["overall_score"] >= 85
    assert not urgent
    assert any("healthy" in r.lower() for r in report["recommendations"])


@pytest.mark.asyncio
async def test_dry_run_report_uses_weighted_formula_not_constants(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    srv._reset_ctx_cache()

    r1 = json.loads(await get_operations_health_report("B0FIXTURE01"))
    r2 = json.loads(await get_operations_health_report("B0FIXTURE01,B0FIXTURE02"))

    assert r1["scoring_version"] == "v2-four-dim"
    assert r1["health_scores"] != {"inventory_risk": 72, "ad_efficiency": 58, "price_competitiveness": 81}
    assert r1["overall_score"] != 70
    # Different ASIN sets can shift price competitiveness average
    assert r1["health_scores"]["inventory_risk"] == r2["health_scores"]["inventory_risk"]
    assert r1["overall_score"] != r2["overall_score"] or len(r2["asins_analyzed"]) > 1


def test_inventory_risk_empty_asins_returns_neutral():
    score, urgent = score_inventory_risk([], [])
    assert score == 50
    assert urgent == []


def test_inventory_risk_asin_not_in_summaries_low_stock():
    # ASIN not found in summaries → qty=0 → s=10
    score, urgent = score_inventory_risk([], ["B0MISSING"])
    assert score == 10
    assert any("B0MISSING" in u for u in urgent)


def test_ad_efficiency_no_spend_no_sales_returns_neutral():
    from amazon_mcp.scoring.operations_health import score_ad_efficiency
    score = score_ad_efficiency({"campaigns": [], "totals": {"spend": 0, "sales": 0}})
    assert 0 <= score <= 100


def test_price_competitiveness_multi_empty_asins():
    from amazon_mcp.scoring.operations_health import score_price_competitiveness_multi
    score = score_price_competitiveness_multi([], {})
    assert score == 50


def test_price_competitiveness_no_buy_box_returns_neutral():
    from amazon_mcp.scoring.operations_health import score_price_competitiveness
    # No buy_box_price → returns 50
    score = score_price_competitiveness("B0001", {})
    assert score == 50


@pytest.mark.asyncio
async def test_get_operations_health_report_includes_account_health(dry_run_env):
    raw = await get_operations_health_report("B0FIXTURE01")
    data = json.loads(raw)
    assert data["scoring_version"] == SCORING_VERSION_V2
    assert "account_health" in data["health_scores"]
    assert data["account_health_detail"]["ok"] is True
