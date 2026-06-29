"""Sales WoW narrative (B5)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from amazon_mcp.reports.sales_trend import (
    WOW_ANOMALY_PCT,
    build_wow_narrative,
    compute_wow_metrics,
)


def _series_14(cur: list[int], prior: list[int]) -> list[dict]:
    rows = []
    for i, u in enumerate(prior):
        rows.append({"date": f"2026-06-{i+2:02d}", "units": u})
    for i, u in enumerate(cur):
        rows.append({"date": f"2026-06-{i+9:02d}", "units": u})
    return rows


def test_compute_wow_metrics_drop():
    series = _series_14([10, 10, 10, 10, 10, 10, 10], [20, 20, 20, 20, 20, 20, 20])
    m = compute_wow_metrics(series)
    assert m["wow_change_pct"] == -50.0
    assert m["anomaly"] is True


def test_build_wow_narrative_links_reorder_alert():
    wow_by = {
        "B0FIXTURE01": compute_wow_metrics(_series_14([8] * 7, [12] * 7)),
    }
    narrative = build_wow_narrative(
        wow_by,
        reorder_alerts=[{"asin": "B0FIXTURE01", "days_of_cover": 4.2}],
        replenishment_recommendations=[],
        low_score_asins=[],
    )
    assert narrative["ok"] is True
    assert narrative["anomaly"] is True
    assert "B0FIXTURE01" in narrative["narrative"]
    assert "4.2" in narrative["narrative"] or "reorder" in narrative["narrative"].lower()
    assert narrative.get("reason")
