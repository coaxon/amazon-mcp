"""Cross-domain decision rules (B4)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from amazon_mcp.scenarios.cross_domain_rules import (
    THRESHOLDS,
    build_rule_context,
    evaluate_cross_domain_rules,
)


def test_pause_ads_low_cover_rule_fires():
    ctx = build_rule_context(
        ad_health={"status": "healthy", "acos": 0.18, "score": 80},
        profit_snapshot={"net_margin_pct": 10.0},
        account_health_check={"ok": True, "metrics": {"ipi_score": 500}},
        reorder_alerts=[{"asin": "B0TEST", "days_of_cover": 4.2}],
        replenishment_recommendations=[],
    )
    actions = evaluate_cross_domain_rules(ctx)
    ids = {a["rule_id"] for a in actions}
    assert "pause_ads_low_cover" in ids
    hit = next(a for a in actions if a["rule_id"] == "pause_ads_low_cover")
    assert "4.2" in hit["reason"]
    assert str(THRESHOLDS["inventory_cover_days_low"]) in hit["reason"]
    assert "18" in hit["reason"] or "0.18" in hit["reason"]


def test_burn_warning_rule_fires():
    ctx = build_rule_context(
        ad_health={"status": "unhealthy", "acos": 0.32, "score": 35},
        profit_snapshot={"net_margin_pct": -3.5, "asins_below_target_margin": []},
        account_health_check={"ok": True, "metrics": {}},
        reorder_alerts=[],
        replenishment_recommendations=[],
    )
    actions = evaluate_cross_domain_rules(ctx)
    assert any(a["rule_id"] == "burn_warning_neg_margin" for a in actions)


def test_rules_include_reason_on_every_action():
    ctx = build_rule_context(
        ad_health={"status": "healthy", "acos": 0.15, "score": 85},
        profit_snapshot={"net_margin_pct": 5.0, "asins_below_target_margin": [{"asin": "B0X", "net_margin_pct": -2}]},
        account_health_check={"ok": True, "metrics": {"ipi_score": 350}},
        reorder_alerts=[{"asin": "B0X", "days_of_cover": 2.0}],
        replenishment_recommendations=[{"asin": "B0Y", "days_of_cover": 45, "urgency": "LOW"}],
    )
    actions = evaluate_cross_domain_rules(ctx)
    for action in actions:
        assert action.get("reason")
        assert action.get("rule_id")
