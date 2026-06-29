"""Daily briefing summary composition."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from amazon_mcp.scenarios.daily_briefing import _build_summary


def test_summary_omits_wow_narrative_duplicate():
    wow = {
        "ok": True,
        "narrative": "Sales vs last week -33.3% (98 vs 147 units)",
        "reason": "stockout driver",
    }
    summary = _build_summary(
        low_count=1,
        inv_alert_count=0,
        price_alert_count=0,
        ad_status="watch",
        wow_narrative=wow,
    )
    assert "Sales vs last week" not in summary
    assert "1 ASIN(s) need attention" in summary
