"""Edition detection — core vs pro (amazon_mcp_pro optional package)."""
from __future__ import annotations

import importlib.util
import os
from typing import Any

PRO_UPGRADE_URL = "https://github.com/coaxon/amazon-mcp#getting-pro"
PRO_CONTACT = "info@coaxon.me"

# Entire domains that require amazon_mcp_pro
PRO_DOMAINS: frozenset[str] = frozenset({
    "insights",
    "notify",
    "billing",
    "features",
    "admin",
    "meli",
    "tiktok",
    "cross_platform",
    "rto_geo",
    "command_center",
    "benchmark",
    "inventory_pool",
    "sync_schedule",
})

# Per-domain actions that require pro (core domain, pro-only action)
PRO_ACTIONS: dict[str, frozenset[str]] = {
    "alerts": frozenset({
        "configure_inventory",
        "add_price_watch",
        "dismiss",
        "manual_check",
    }),
    "inventory": frozenset({
        "reorder_calculator",
        "restock_recommendations",
        "ipi_score",
        "aging_inventory",
        "fnsku_reorder",
    }),
    "fulfillment": frozenset({"reimbursement_summary"}),
}

# MCP tools / scenarios that require pro (server-level)
PRO_SCENARIOS: frozenset[str] = frozenset({
    "daily_briefing",
    "profit_protection",
    "competitor_monitor",
    "inventory_guardian",
})


def has_pro() -> bool:
    if os.environ.get("AMAZON_MCP_FORCE_CORE", "").strip().lower() in ("1", "true", "yes"):
        return False
    return importlib.util.find_spec("amazon_mcp_pro") is not None


def edition() -> str:
    return "pro" if has_pro() else "core"


def is_pro_required(domain: str, action: str = "") -> bool:
    if domain in PRO_DOMAINS:
        return True
    actions = PRO_ACTIONS.get(domain)
    return bool(actions and action in actions)


def pro_required_response(
    *,
    domain: str = "",
    action: str = "",
    feature: str = "",
) -> dict[str, Any]:
    label = feature or (f"{domain}.{action}" if domain else "pro_feature")
    return {
        "ok": False,
        "error": "pro_required",
        "edition": "core",
        "feature": label,
        "message": (
            "此功能需要 Amazon MCP Pro（多租户、场景编排、主动监控、Slack 集成等）。"
            f"联系定制部署或参见 Getting Pro：{PRO_CONTACT} · {PRO_UPGRADE_URL}"
        ),
        "upgrade": {
            "install": "Pro is not on PyPI — see Getting Pro: https://github.com/coaxon/amazon-mcp#getting-pro",
            "docs": PRO_UPGRADE_URL,
            "contact": PRO_CONTACT,
        },
    }


def pro_required_scenario(scenario: str) -> dict[str, Any]:
    return pro_required_response(feature=f"run_scenario:{scenario}")
