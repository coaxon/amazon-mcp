"""reorder_calculator — reorder point formula and daily_briefing integration."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.monitor.alert_store import AlertStore
from amazon_mcp.scenarios.reorder_calculator import compute_reorder_row, build_reorder_calculations
from fixtures.fixture_sp_client import FixtureSPClient


def test_compute_reorder_row_below_point():
    row = compute_reorder_row(
        asin="B0TEST",
        current_inventory=8,
        daily_sales_rate=12.0,
        lead_time_days=14,
        safety_stock_days=14,
        data_quality="estimated_default",
        account_health={"ok": True, "metrics": {"ipi_score": 380}},
    )
    assert row["ok"] is True
    assert row["reorder_point"] == pytest.approx(336.0)
    assert row["below_reorder_point"] is True
    assert row["suggested_order_qty"] == 328
    assert any("overstock" in h for h in row["risk_hints"])


@pytest.mark.asyncio
async def test_build_reorder_calculations_fixture(tmp_path):
    store = AlertStore(str(tmp_path / "reorder.db"))
    sp = FixtureSPClient()
    result = await build_reorder_calculations(sp=sp, alert_store=store, asins=["B0FIXTURE01", "B0FIXTURE02"])
    assert result["ok"] is True
    assert result["alert_count"] >= 1
    alert_asins = {a["asin"] for a in result["reorder_alerts"]}
    assert "B0FIXTURE01" in alert_asins


@pytest.mark.asyncio
async def test_reorder_calculator_domain_dispatch(monkeypatch):
    import amazon_mcp.server as srv
    from amazon_mcp.server import run_scenario
    from amazon_mcp.tools.registry import dispatch_domain

    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    srv._reset_ctx_cache()

    raw = await dispatch_domain("inventory", "reorder_calculator", "{}", "default")
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    payload = envelope.get("data") or envelope
    assert "calculations" in payload
    assert payload["alert_count"] >= 1
