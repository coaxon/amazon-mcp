import pytest
import os
import sqlite3
import asyncio
from pathlib import Path
from amazon_mcp.monitor.thresholds import InventoryThreshold, PriceWatch, AlertRecord
from amazon_mcp.monitor.alert_store import AlertStore
from amazon_mcp.monitor.alert_engine import AlertEngine

# Need to import server tools for E2E testing
from amazon_mcp.server import (
    configure_inventory_alert,
    add_price_watch,
    get_pending_alerts,
    dismiss_alert,
    get_alert_config,
    _get_store,
    _alert_engine,
    _lifespan
)
import json

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_alerts.db"
    store = AlertStore(str(db_path))
    yield store
    # Cleanup
    if db_path.exists():
        db_path.unlink()

def test_alert_store_crud(temp_db):
    # Test Inventory
    th = InventoryThreshold(sku="TEST-SKU", asin="B0001", min_qty=10)
    temp_db.upsert_inventory_threshold(th)
    
    thresholds = temp_db.list_inventory_thresholds()
    assert len(thresholds) == 1
    assert thresholds[0]["sku"] == "TEST-SKU"
    assert thresholds[0]["min_qty"] == 10

    # Test Price
    pw = PriceWatch(asin="B0002", baseline_price=29.99, alert_pct=0.1)
    temp_db.upsert_price_watch(pw)
    
    watches = temp_db.list_price_watches()
    assert len(watches) == 1
    assert watches[0]["asin"] == "B0002"

    # Test Alerts
    alert = AlertRecord(
        alert_type="LOW_INVENTORY",
        title="Test Alert",
        asin="B0001",
        sku="TEST-SKU",
        data={"qty": 5}
    )
    temp_db.add_alert(alert)
    
    pending = temp_db.get_pending_alerts()
    assert len(pending) == 1
    assert temp_db.count_pending() == 1
    assert pending[0]["alert_id"] == alert.alert_id

    # Dismiss
    assert temp_db.dismiss_alert(alert.alert_id) is True
    assert temp_db.count_pending() == 0

@pytest.mark.asyncio
async def test_alert_engine_dry_run(temp_db):
    engine = AlertEngine(store=temp_db, dry_run=True)
    
    # Add thresholds
    temp_db.upsert_inventory_threshold(InventoryThreshold("SKU1", "ASIN1", 100))
    temp_db.upsert_price_watch(PriceWatch("ASIN2", 50.0, 0.1))
    
    # Run checks (dry_run simulates alerts 50% of the time, so we might need multiple runs)
    # We will force the random seed or just run it enough times
    import random
    random.seed(42) # Ensure predictable outcome if possible, or just run until we get an alert
    
    for _ in range(10):
        await engine.check_inventory()
        await engine.check_prices()
        if temp_db.count_pending() > 0:
            break
            
    assert temp_db.count_pending() > 0

@pytest.mark.asyncio
async def test_server_tools():
    # E2E Test on server tools
    
    # 1. Configure threshold
    res1 = json.loads(await configure_inventory_alert("SKU-999", "B000999", 15))
    assert res1["ok"] is True
    
    # 2. Get config
    res2 = json.loads(await get_alert_config())
    assert res2["ok"] is True
    
    # Check it exists
    skus = [t["sku"] for t in res2["inventory_thresholds"]]
    assert "SKU-999" in skus
    
    # 3. get_pending_alerts dry_run (from server's _alert_store / _alert_engine)
    # We won't test full mock generation here because it modifies the global store,
    # but we can check if it returns valid json
    res3 = json.loads(await get_pending_alerts(limit=5))
    assert res3["ok"] is True
    assert "alerts" in res3
    
    # 4. dismiss all
    res4 = json.loads(await dismiss_alert("ALL"))
    assert res4["ok"] is True
