"""Replenishment recommendation — P0.5."""
from __future__ import annotations

import json
from datetime import date

import pytest

from amazon_mcp.monitor.alert_store import AlertStore
from amazon_mcp.scenarios.replenishment import (
    compute_replenishment_row,
    build_replenishment_recommendations,
)
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from fixtures.fixture_sp_client import FixtureSPClient


def test_compute_overdue():
    row = compute_replenishment_row(
        asin="B0TEST",
        current_inventory=8,
        daily_sales_rate=12.0,
        lead_time_days=14,
        data_quality="estimated_default_lead_time",
        today=date(2026, 6, 14),
    )
    assert row is not None
    assert row["urgency"] == "OVERDUE"
    assert row["days_of_cover"] == pytest.approx(0.67, abs=0.01)
    assert row["recommended_qty"] > 0


def test_compute_urgent():
    row = compute_replenishment_row(
        asin="B0TEST",
        current_inventory=160,
        daily_sales_rate=8.0,
        lead_time_days=14,
        data_quality="configured",
        today=date(2026, 6, 14),
    )
    assert row is not None
    assert row["urgency"] == "URGENT"
    assert row["data_quality"] == "configured"


def test_compute_ok_returns_none():
    row = compute_replenishment_row(
        asin="B0TEST",
        current_inventory=45,
        daily_sales_rate=2.0,
        lead_time_days=14,
        data_quality="estimated_default_lead_time",
        today=date(2026, 6, 14),
    )
    assert row is None


@pytest.mark.asyncio
async def test_fixture_mixed_overdue_and_ok(tmp_path):
    store = AlertStore(str(tmp_path / "rep.db"))
    sp = FixtureSPClient()
    recs = await build_replenishment_recommendations(
        sp=sp,
        alert_store=store,
        asins=["B0FIXTURE01", "B0FIXTURE02"],
        today=date(2026, 6, 14),
    )
    asins = {r["asin"] for r in recs}
    assert "B0FIXTURE01" in asins
    assert "B0FIXTURE02" not in asins
    overdue = next(r for r in recs if r["asin"] == "B0FIXTURE01")
    assert overdue["urgency"] == "OVERDUE"
    assert overdue["data_quality"] == "estimated_default_lead_time"


@pytest.mark.asyncio
async def test_configured_lead_time_quality(tmp_path):
    store = AlertStore(str(tmp_path / "rep2.db"))
    store.set_replenishment_lead_time("B0FIXTURE01", 21)
    sp = FixtureSPClient()
    recs = await build_replenishment_recommendations(
        sp=sp,
        alert_store=store,
        asins=["B0FIXTURE01"],
        today=date(2026, 6, 14),
    )
    assert len(recs) == 1
    assert recs[0]["lead_time_days"] == 21
    assert recs[0]["data_quality"] == "configured"


@pytest.mark.asyncio
async def test_daily_briefing_includes_replenishment(monkeypatch, tmp_path):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    import amazon_mcp.server as srv
    from amazon_mcp.server import run_scenario

    srv._reset_ctx_cache()
    store = AlertStore(str(tmp_path / "brief.db"))
    monkeypatch.setattr(srv, "_alert_store", store)
    raw = await run_scenario("daily_briefing")
    data = json.loads(raw)
    recs = data.get("replenishment_recommendations") or []
    assert any(r.get("asin") == "B0FIXTURE01" for r in recs)
    assert "reorder" in data.get("summary", "").lower()
