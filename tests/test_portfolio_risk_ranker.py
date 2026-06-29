"""Portfolio risk ranker (B6)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from amazon_mcp.scenarios.portfolio_risk_ranker import rank_portfolio_risks


def test_rank_portfolio_top5_with_reasons():
    summaries = [
        {"asin": "B0LOW", "fulfillableQuantity": 2},
        {"asin": "B0OK", "fulfillableQuantity": 80},
    ]
    low = [{
        "asin": "B0LOW",
        "overall_score": 32,
        "top_issue": "Inventory risk",
        "health_scores": {"inventory_risk": 20, "ad_efficiency": 60, "price_competitiveness": 40},
    }]
    ranked = rank_portfolio_risks(
        ["B0LOW", "B0OK"],
        summaries,
        low,
        ad_score=60,
        reorder_alerts=[{"asin": "B0LOW", "days_of_cover": 4.2}],
        profit_snapshot={"by_asin": {"B0LOW": {"net_margin_pct": -2.0}}},
        limit=5,
    )
    assert len(ranked) == 2
    assert ranked[0]["asin"] == "B0LOW"
    assert ranked[0].get("reason")
    assert "inventory" in ranked[0]["reason"].lower() or "4.2" in ranked[0]["reason"]
