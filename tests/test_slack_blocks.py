"""Block Kit — full composite briefing surfaced in Slack."""
from __future__ import annotations

import json
from pathlib import Path

from amazon_mcp.integrations.slack_blocks import build_daily_briefing_blocks

_FIXTURE = Path(__file__).resolve().parents[1] / "docs/fixtures/clean_daily_briefing_demo.json"


def _body(blocks: list[dict]) -> str:
    parts: list[str] = []
    for b in blocks:
        if b.get("type") == "header":
            parts.append(b["text"]["text"])
        elif b.get("type") == "section" and "text" in b:
            parts.append(b["text"]["text"])
        elif b.get("type") == "context":
            for el in b.get("elements", []):
                parts.append(el.get("text", ""))
    return "\n".join(parts)


def test_profit_snapshot_includes_fees_and_winners():
    briefing = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    blocks = build_daily_briefing_blocks(briefing)
    body = _body(blocks)
    assert "Profit detail" in body
    assert "Revenue" in body
    assert "Fee breakdown" in body
    assert "Referral" in body
    assert "B0FIXTURE02" in body
    assert "-8.2%" in body
    assert "B0FIXTURE01" in body
    assert "on target" in body


def test_composite_sections_and_buttons():
    briefing = {
        "date": "2026-06-14",
        "scoring_version": "v1-weighted",
        "summary": "1 ASIN(s) need attention",
        "profit_snapshot": {"period": "last 30 days", "net_margin_pct": 10.0, "target_margin_pct": 15.0},
        "ad_health": {"acos": 0.228, "status": "watch", "score": 60},
        "price_changes": [
            {
                "asin": "B0FIXTURE01",
                "your_price": 29.99,
                "buy_box_price": 27.99,
                "price_gap_vs_buybox": 2.0,
                "note": "Above Buy Box",
            }
        ],
        "recommended_actions": [
            {"urgency": "HIGH", "action": "Review B0FIXTURE01", "source": "health_score"},
            {"urgency": "CRITICAL", "action": "Reorder B0FIXTURE01", "source": "replenishment"},
        ],
        "price_alerts": [
            {"alert_id": "p1", "alert_type": "BUY_BOX_LOST", "title": "Buy Box lost", "asin": "B0FIXTURE01", "severity": "WARN"},
        ],
        "low_score_asins": [{
            "asin": "B0FIXTURE01",
            "overall_score": 37,
            "top_issue": "Pricing risk",
            "health_scores": {"inventory_risk": 30, "ad_efficiency": 60, "price_competitiveness": 25},
        }],
        "replenishment_recommendations": [
            {"asin": "B0FIXTURE02", "recommended_qty": 200, "latest_order_date": "2026-06-20", "days_of_cover": 10, "urgency": "URGENT", "current_inventory": 50, "daily_sales_rate": 5},
            {"asin": "B0FIXTURE01", "recommended_qty": 520, "latest_order_date": "2026-05-31", "days_of_cover": 0.67, "urgency": "OVERDUE", "current_inventory": 8, "daily_sales_rate": 12},
        ],
        "inventory_alerts": [],
        "meta": {"monitored_asin_count": 2, "pending_alert_count": 1},
    }
    blocks = build_daily_briefing_blocks(briefing)
    body = _body(blocks)
    assert "Price & competition watch" in body
    assert "Buy Box" in body
    assert "Price alert" in body
    assert "Scores:" in body
    assert "Replenishment URGENT" in body
    assert "Replenishment OVERDUE" in body
    assert "replenishment" in body
    assert "2 ASINs" in body
    actions = [b for b in blocks if b.get("type") == "actions"]
    assert len(actions) >= 3  # rationale toggles + price ack + health ack + preview
    preview_ids = [
        el["action_id"]
        for b in actions for el in b.get("elements", [])
    ]
    assert "preview_inbound_plan" in preview_ids


def test_daily_briefing_blocks_include_finance_and_reorder():
    from amazon_mcp.integrations.slack_blocks import build_daily_briefing_blocks

    briefing = {
        "date": "2026-06-15",
        "summary": "Test summary",
        "fba_reimbursement_check": {"ok": True, "period_days": 30, "total_reimbursed_usd": 120.5, "reimbursement_count": 2},
        "account_health_check": {"ok": True, "account_health_score": 88, "metrics": {"ipi_score": 512, "order_defect_rate": 0.004}},
        "reorder_alerts": [{
            "asin": "B0FIXTURE01",
            "current_inventory": 8,
            "reorder_point": 336,
            "suggested_order_qty": 328,
            "daily_sales_rate": 12,
            "lead_time_days": 14,
            "safety_stock_days": 14,
            "risk_hints": [],
        }],
        "profit_snapshot": {},
        "meta": {},
    }
    blocks = build_daily_briefing_blocks(briefing)
    joined = json.dumps(blocks)
    assert "FBA reimbursements" in joined
    assert "Account health score" in joined
    assert "Reorder point alerts" in joined
    assert "B0FIXTURE01" in joined


def test_chart_blocks_degrade_on_localhost_url():
    from amazon_mcp.integrations.slack_blocks import build_daily_briefing_blocks
    briefing = {
        "date": "2026-06-15",
        "summary": "s",
        "briefing_assets": {
            "ok": True,
            "chart_url": "http://127.0.0.1:8780/briefing/assets/t/sales_trend.png",
            "pdf_url": "http://127.0.0.1:8780/briefing/assets/t/briefing_report.pdf",
            "chart_asins": ["B0FIXTURE01"],
        },
        "meta": {},
    }
    blocks = build_daily_briefing_blocks(briefing)
    blob = __import__("json").dumps(blocks)
    assert '"type": "image"' not in blob and '"type":"image"' not in blob.replace(" ", "")
    assert "AMAZON_MCP_PUBLIC_BASE_URL" in blob

def test_summary_formatted_as_bullets():
    from amazon_mcp.integrations.slack_blocks import build_daily_briefing_blocks

    briefing = {
        "date": "2026-06-15",
        "summary": "1 ASIN(s) need attention, No pending alerts, ads need monitoring",
        "meta": {},
    }
    blocks = build_daily_briefing_blocks(briefing)
    section = next(b for b in blocks if b.get("type") == "section")
    body = section["text"]["text"]
    assert "*At a glance*" in body
    assert "- 1 ASIN(s) need attention" in body
    assert "- ads need monitoring" in body


def test_block_order_chart_before_interactive_actions():
    from amazon_mcp.integrations.slack_blocks import build_daily_briefing_blocks

    briefing = {
        "date": "2026-06-15",
        "summary": "Test",
        "price_alerts": [{"alert_id": "p1", "title": "Buy Box", "asin": "B0X", "severity": "WARN"}],
        "briefing_assets": {
            "ok": True,
            "chart_url": "https://example.com/briefing/assets/t/sales_trend.png",
            "pdf_url": "https://example.com/briefing/assets/t/briefing_report.pdf",
            "chart_asins": ["B0X"],
        },
        "meta": {},
    }
    blocks = build_daily_briefing_blocks(briefing)
    types = [b.get("type") for b in blocks]
    image_idx = types.index("image")
    actions_idx = types.index("actions")
    assert image_idx < actions_idx


def test_recommended_actions_use_dash_bullets():
    from amazon_mcp.integrations.slack_blocks import build_daily_briefing_blocks

    briefing = {
        "date": "2026-06-15",
        "summary": "s",
        "recommended_actions": [{
            "urgency": "HIGH",
            "action": "Fix pricing",
            "source": "health",
            "reason": "Price competitiveness score below threshold",
        }],
        "meta": {},
    }
    blocks = build_daily_briefing_blocks(briefing)
    joined = "\n".join(
        b["text"]["text"] for b in blocks if b.get("type") == "section" and "text" in b
    )
    assert "- *[HIGH]* Fix pricing" in joined
    blob = json.dumps(blocks)
    assert "Decision rationale" in blob
    assert '"expand": false' in blob or '"expand":false' in blob.replace(" ", "")
    assert "→" not in joined



def test_decision_copilot_slack_sections():
    briefing = {
        "date": "2026-06-15",
        "summary": "Test",
        "wow_narrative": {
            "ok": True,
            "narrative": "Sales vs last week -12.0% (77 vs 88 units)",
            "reason": "Units 77 vs 88 prior week (-12.5% WoW, anomaly threshold ±20%)",
            "anomaly": False,
        },
        "portfolio_risk_top5": [{
            "asin": "B0FIXTURE01",
            "overall_score": 37,
            "reason": "Pricing competitiveness score 25/100 is the lowest weighted factor → `B0FIXTURE01` needs attention",
        }],
        "recommended_actions": [{
            "urgency": "HIGH",
            "action": "Pause or reduce ad spend until inbound restock improves cover",
            "source": "cross_domain_rule",
            "reason": "Inventory cover 4.2d < 7.0d threshold AND ACoS 18.0% < healthy ceiling 25%",
        }],
        "profit_snapshot": {},
        "ad_health": {},
    }
    blocks = build_daily_briefing_blocks(briefing)
    body = _body(blocks)
    blob = json.dumps(blocks)
    assert "Week-over-week sales" in body
    assert "Top 5 today" in body
    assert "Decision rationale" in blob
    assert '"expand": false' in blob or '"expand":false' in blob.replace(" ", "")
    assert "Show rationale" not in blob
    assert "B0FIXTURE01" in body

def test_rationale_in_section_with_expand_false():
    from amazon_mcp.integrations.slack_blocks import _section_with_rationale

    block = _section_with_rationale(
        "*Week-over-week sales*\n- Sales vs last week -12.0%",
        "Units down due to stockout on B0FIXTURE01",
        show_rationale=True,
    )
    assert block["type"] == "section"
    assert block["expand"] is False
    assert "Decision rationale" in block["text"]["text"]
    assert "stockout" in block["text"]["text"]

    plain = _section_with_rationale("conclusion only", "", show_rationale=True)
    assert "expand" not in plain


def test_briefing_prefs_filter_sections():
    from amazon_mcp.integrations.slack_briefing_prefs import BriefingDisplayPrefs
    from amazon_mcp.integrations.slack_blocks import build_daily_briefing_blocks

    briefing = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    prefs = BriefingDisplayPrefs(sections={k: (k != "profit_detail") for k in BriefingDisplayPrefs.from_dict({}).sections})
    blocks = build_daily_briefing_blocks(briefing, prefs)
    body = _body(blocks)
    assert "Profit detail" not in body


def test_collapsed_message_shorter_than_inline_rationale():
    briefing = {
        "date": "2026-06-15",
        "summary": "1 ASIN(s) need attention, ads need monitoring",
        "wow_narrative": {
            "ok": True,
            "narrative": "Sales vs last week -33.3% (98 vs 147 units)",
            "reason": "B0FIXTURE01 replenishment OVERDUE — possible stockout impact",
        },
        "portfolio_risk_top5": [{
            "asin": "B0FIXTURE01",
            "overall_score": 37,
            "reason": "Pricing competitiveness score 25/100 is the lowest weighted factor",
        }],
        "reorder_alerts": [{
            "asin": "B0FIXTURE01",
            "current_inventory": 8,
            "reorder_point": 336,
            "suggested_order_qty": 328,
            "daily_sales_rate": 12,
            "lead_time_days": 14,
            "safety_stock_days": 14,
            "risk_hints": [],
        }],
        "meta": {},
    }
    collapsed = build_daily_briefing_blocks(briefing)
    inline = json.dumps(collapsed)
    # simulate old inline style length
    old_style_extra = (
        "Decision rationale: B0FIXTURE01 replenishment OVERDUE — possible stockout impact"
        + "Decision rationale: Pricing competitiveness"
        + "Decision rationale: On-hand 8 < reorder point"
    )
    assert len(inline) < len(inline) + len(old_style_extra)
    assert "Decision rationale" in inline
    assert '"expand": false' in inline or '"expand":false' in inline.replace(" ", "")
    assert "Show rationale" not in inline

