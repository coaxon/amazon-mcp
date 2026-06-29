"""Integration: fixture SP client → AlertEngine → alerts.db → notifier."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.monitor.alert_engine import AlertEngine
from amazon_mcp.monitor.alert_store import AlertStore
from amazon_mcp.monitor.notifier import NotificationRouter, NotifierConfig
from amazon_mcp.monitor.thresholds import InventoryThreshold, PriceWatch
from fixtures.fixture_sp_client import FixtureSPClient


class CaptureNotifier(NotificationRouter):
    def __init__(self):
        super().__init__(NotifierConfig())
        self.sent: list[dict] = []

    async def route(self, alert):
        self.sent.append({"alert_id": alert.alert_id, "type": alert.alert_type, "sku": alert.sku, "asin": alert.asin})
        return {"captured": True}


@pytest.mark.asyncio
async def test_live_inventory_chain_fixture_to_db_and_notifier():
    store = AlertStore(db_path=f"{tempfile.mkdtemp()}/alerts.db")
    store.upsert_inventory_threshold(InventoryThreshold(sku="SKU-FIX-001", asin="B0FIXTURE01", min_qty=20))
    engine = AlertEngine(store=store, sp_client=FixtureSPClient(), dry_run=False, notifier=CaptureNotifier())
    count = await engine.check_inventory()
    assert count == 1
    assert store.get_pending_alerts()[0]["sku"] == "SKU-FIX-001"
    await asyncio.sleep(0.05)
    assert engine.notifier.sent[0]["type"] == "LOW_INVENTORY"


@pytest.mark.asyncio
async def test_live_price_chain_fixture_to_db_and_notifier():
    store = AlertStore(db_path=f"{tempfile.mkdtemp()}/alerts.db")
    store.upsert_price_watch(PriceWatch(asin="B0FIXTURE01", baseline_price=35.00, alert_pct=0.05))
    engine = AlertEngine(store=store, sp_client=FixtureSPClient(), dry_run=False, notifier=CaptureNotifier())
    count = await engine.check_prices()
    assert count == 1
    assert store.get_pending_alerts()[0]["alert_type"] == "PRICE_CHANGE"


@pytest.mark.asyncio
async def test_run_once_full_chain():
    store = AlertStore(db_path=f"{tempfile.mkdtemp()}/alerts.db")
    store.upsert_inventory_threshold(InventoryThreshold(sku="SKU-FIX-001", asin="B0FIXTURE01", min_qty=20))
    store.upsert_price_watch(PriceWatch(asin="B0FIXTURE01", baseline_price=35.00, alert_pct=0.05))
    engine = AlertEngine(store=store, sp_client=FixtureSPClient(), dry_run=False, notifier=CaptureNotifier())
    result = await engine.run_once()
    assert result["new_alerts_generated"] == 2
    await asyncio.sleep(0.05)
    assert len(engine.notifier.sent) == 2
