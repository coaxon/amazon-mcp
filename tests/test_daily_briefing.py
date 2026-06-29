"""daily_briefing scenario — healthy / partial / multi-alert scenarios."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.monitor.alert_store import AlertStore
from amazon_mcp.monitor.thresholds import AlertRecord, InventoryThreshold, PriceWatch
import amazon_mcp.server as srv
from amazon_mcp.server import run_scenario


@pytest.fixture
def dry_run_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    monkeypatch.setenv("AMAZON_COGS_DB_PATH", str(tmp_path / "cogs.db"))
    srv._reset_ctx_cache()
    srv._cogs_store_cache.clear()


@pytest.fixture
def temp_store(tmp_path):
    return AlertStore(str(tmp_path / "briefing_alerts.db"))


def _seed_healthy(store: AlertStore) -> None:
    store.upsert_inventory_threshold(InventoryThreshold("SKU-FIX-002", "B0FIXTURE02", 10))
    store.upsert_price_watch(PriceWatch("B0FIXTURE02", 28.99, 0.05))


def _seed_partial(store: AlertStore) -> None:
    store.upsert_inventory_threshold(InventoryThreshold("SKU-FIX-001", "B0FIXTURE01", 20))
    store.add_alert(AlertRecord(
        alert_type="LOW_INVENTORY",
        severity="WARN",
        title="Low inventory threshold",
        detail="Fulfillable 8 < 20",
        asin="B0FIXTURE01",
        sku="SKU-FIX-001",
        data={"qty": 8, "threshold": 20},
    ))


def _seed_multi(store: AlertStore) -> None:
    store.upsert_inventory_threshold(InventoryThreshold("SKU-FIX-001", "B0FIXTURE01", 20))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-FIX-002", "B0FIXTURE02", 50))
    store.upsert_price_watch(PriceWatch("B0FIXTURE01", 29.99, 0.05))
    store.add_alert(AlertRecord(
        alert_type="LOW_INVENTORY", severity="CRITICAL", title="Stockout risk",
        asin="B0FIXTURE01", sku="SKU-FIX-001", detail="qty=8",
    ))
    store.add_alert(AlertRecord(
        alert_type="OUT_OF_STOCK", severity="CRITICAL", title="SKU out of stock",
        asin="B0STOCK", sku="SKU-X", detail="qty=0",
    ))
    store.add_alert(AlertRecord(
        alert_type="PRICE_CHANGE", severity="WARN", title="Competitor price drop",
        asin="B0FIXTURE01", detail="Price moved 6%",
    ))


@pytest.mark.asyncio
async def test_daily_briefing_all_healthy(dry_run_env, temp_store, monkeypatch):
    _seed_healthy(temp_store)
    monkeypatch.setattr(srv, "_alert_store", temp_store)

    raw = await run_scenario("daily_briefing")
    data = json.loads(raw)

    assert data["ok"] is True
    assert data["scenario"] == "daily_briefing"
    assert data["scoring_version"] == "v1-weighted"
    assert data["inventory_alerts"] == []
    assert data["low_score_asins"] == []
    assert data["ad_health"]["status"] in ("healthy", "watch")
    assert "No low-score ASINs" in data["summary"]
    assert data["summary"] != ""
    ps = data["profit_snapshot"]
    assert ps["period"] == "last 30 days"
    assert ps["total_revenue"] == 4480.0
    assert "referral" in ps["total_fees_breakdown"]
    assert -20 <= ps["net_margin_pct"] <= 25
    assert any(r["asin"] == "B0FIXTURE02" for r in ps["asins_below_target_margin"])
    assert "fba_reimbursement_check" in data
    assert "returns_summary_check" in data
    assert data["account_health_check"].get("ok") is True
    assert isinstance(data.get("reorder_alerts"), list)
    assert isinstance(data.get("portfolio_risk_top5"), list)
    assert data.get("wow_narrative", {}).get("ok") is True


@pytest.mark.asyncio
async def test_daily_briefing_partial_alerts(dry_run_env, temp_store, monkeypatch):
    _seed_partial(temp_store)
    monkeypatch.setattr(srv, "_alert_store", temp_store)

    raw = await run_scenario("daily_briefing")
    data = json.loads(raw)

    assert data["ok"] is True
    assert len(data["inventory_alerts"]) == 1
    assert len(data["low_score_asins"]) >= 1
    assert data["low_score_asins"][0]["asin"] == "B0FIXTURE01"
    assert data["low_score_asins"][0]["overall_score"] < 60
    assert "inventory alert" in data["summary"].lower()
    assert any(a["source"] == "pending_alert" for a in data["recommended_actions"])
    assert data.get("wow_narrative", {}).get("narrative")
    assert len(data.get("portfolio_risk_top5") or []) >= 1
    cross = [a for a in data["recommended_actions"] if a.get("source") == "cross_domain_rule"]
    assert cross and all(a.get("reason") for a in cross)


@pytest.mark.asyncio
async def test_daily_briefing_multi_alerts(dry_run_env, temp_store, monkeypatch):
    _seed_multi(temp_store)
    monkeypatch.setattr(srv, "_alert_store", temp_store)

    raw = await run_scenario("daily_briefing")
    data = json.loads(raw)

    assert data["ok"] is True
    assert len(data["inventory_alerts"]) >= 2
    assert len(data["low_score_asins"]) >= 1
    assert len(data["price_changes"]) >= 1
    assert len(data["recommended_actions"]) >= 3
    assert data["meta"]["pending_alert_count"] >= 3
    # Multi scenario summary differs from healthy
    assert "attention" in data["summary"].lower() or "alert" in data["summary"].lower()


@pytest.mark.asyncio
async def test_daily_briefing_scenarios_produce_distinct_summaries(
    dry_run_env, tmp_path, monkeypatch,
):
    """Non-constant verification — different store seeds → different briefings."""
    summaries = []
    for seed_fn in (_seed_healthy, _seed_partial, _seed_multi):
        store = AlertStore(str(tmp_path / f"db_{seed_fn.__name__}.db"))
        seed_fn(store)
        monkeypatch.setattr(srv, "_alert_store", store)
        data = json.loads(await run_scenario("daily_briefing"))
        summaries.append(data["summary"])

    assert len(set(summaries)) >= 2
    assert summaries[0] != summaries[2]


@pytest.mark.asyncio
async def test_daily_briefing_phase2_partial_failure(dry_run_env, temp_store, monkeypatch):
    """Phase-2 exception in one sub-task degrades gracefully; briefing still returns ok."""
    import amazon_mcp.scenarios.daily_briefing as db_mod

    _seed_healthy(temp_store)
    monkeypatch.setattr(srv, "_alert_store", temp_store)

    original_profit_fn = db_mod.build_profit_snapshot

    async def _exploding_profit(*args, **kwargs):
        raise RuntimeError("simulated profit_snapshot failure")

    monkeypatch.setattr(db_mod, "build_profit_snapshot", _exploding_profit)

    raw = await run_scenario("daily_briefing")
    data = json.loads(raw)

    assert data["ok"] is True
    assert data["profit_snapshot"] == {}
    assert isinstance(data["low_score_asins"], list)
    assert isinstance(data["price_changes"], list)
