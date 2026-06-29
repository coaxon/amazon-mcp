"""Decision actions must carry explicit reason for Slack/briefing."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from amazon_mcp.scenarios.daily_briefing import (
    _health_score_reason,
    _reorder_point_reason,
    _replenishment_reason,
)


def test_replenishment_reason_includes_cover_and_urgency():
    rec = {
        "days_of_cover": 0.67,
        "lead_time_days": 14,
        "urgency": "OVERDUE",
        "current_inventory": 8,
        "daily_sales_rate": 12.0,
    }
    r = _replenishment_reason(rec)
    assert "0.67" in r and "OVERDUE" in r and "8" in r


def test_reorder_reason_includes_rop():
    rec = {
        "current_inventory": 8,
        "reorder_point": 336.0,
        "lead_time_days": 14,
        "safety_stock_days": 14,
        "daily_sales_rate": 12.0,
        "risk_hints": ["stockout_risk"],
    }
    r = _reorder_point_reason(rec)
    assert "336" in r and "stockout_risk" in r


def test_health_score_reason_includes_dims():
    row = {
        "overall_score": 37,
        "top_issue": "Pricing risk",
        "health_scores": {
            "inventory_risk": 30,
            "ad_efficiency": 60,
            "price_competitiveness": 25,
        },
    }
    r = _health_score_reason(row)
    assert "37" in r and "Pricing risk" in r and "price_competitiveness=25" in r
