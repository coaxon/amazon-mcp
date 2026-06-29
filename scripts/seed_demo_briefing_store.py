#!/usr/bin/env python3
"""Seed demo AlertStore(s) showcasing all system features.

Usage:
    python scripts/seed_demo_briefing_store.py            # seed default tenant
    python scripts/seed_demo_briefing_store.py --multi    # seed 3 demo tenants
    python scripts/seed_demo_briefing_store.py --tenant seller_B
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from amazon_mcp.monitor.alert_store import AlertStore
from amazon_mcp.monitor.thresholds import AlertRecord, InventoryThreshold, PriceWatch

UTC = timezone.utc


def _ts(hours_ago: float = 0) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()


def seed_tenant(store: AlertStore, *, reset: bool = True, scenario: str = "default") -> dict:
    """Seed one tenant's AlertStore with demo data.

    scenario:
        "default" — established seller, mixed alert landscape
        "crisis"  — out-of-stock + buy box lost, high-urgency
        "growth"  — new SKUs, ad campaigns, ACOS spike
    """
    if reset:
        db = Path(store.db_path)
        for ext in ("", "-shm", "-wal"):
            p = db.parent / (db.name + ext)
            if p.exists():
                p.unlink()
        store = AlertStore(db_path=str(db))

    if scenario == "default":
        _seed_default(store)
    elif scenario == "crisis":
        _seed_crisis(store)
    elif scenario == "growth":
        _seed_growth(store)
    else:
        _seed_default(store)

    return {
        "status": "ok",
        "scenario": scenario,
        "db_path": store.db_path,
        "thresholds": len(store.list_inventory_thresholds()),
        "price_watches": len(store.list_price_watches()),
        "pending_alerts": len(store.get_pending_alerts(limit=200)),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Scenario A — "default": established seller, realistic mixed landscape
# ──────────────────────────────────────────────────────────────────────────────
def _seed_default(store: AlertStore) -> None:
    # Inventory thresholds — 6 SKUs
    store.upsert_inventory_threshold(InventoryThreshold("SKU-GADGET-001", "B0GADGET001", 30))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-GADGET-002", "B0GADGET002", 20))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-HOME-001",   "B0HOME0001",  50))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-HOME-002",   "B0HOME0002",  25))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-SPORT-001",  "B0SPORT001",  15))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-SPORT-002",  "B0SPORT002",  10))

    # Price watches
    store.upsert_price_watch(PriceWatch("B0GADGET001", 49.99, 0.05))
    store.upsert_price_watch(PriceWatch("B0GADGET002", 34.99, 0.05))
    store.upsert_price_watch(PriceWatch("B0HOME0001",  89.99, 0.08))
    store.upsert_price_watch(PriceWatch("B0HOME0002",  24.99, 0.06))
    store.upsert_price_watch(PriceWatch("B0SPORT001",  19.99, 0.10))

    # Replenishment lead times
    store.set_replenishment_lead_time("B0GADGET001", 21)
    store.set_replenishment_lead_time("B0GADGET002", 14)
    store.set_replenishment_lead_time("B0HOME0001",  28)
    store.set_replenishment_lead_time("B0HOME0002",  14)
    store.set_replenishment_lead_time("B0SPORT001",  7)

    # ── CRITICAL alerts → triggers real-time Slack push ─────────────────────
    store.add_alert(AlertRecord(
        alert_type="OUT_OF_STOCK",
        severity="CRITICAL",
        title="B0GADGET001 out of stock",
        detail="Fulfillable quantity dropped to 0 — listing suppressed",
        asin="B0GADGET001", sku="SKU-GADGET-001",
        data={"qty": 0, "threshold": 30, "days_since_restock": 12},
        created_at=_ts(1.5),
    ))
    store.add_alert(AlertRecord(
        alert_type="BUY_BOX_LOST",
        severity="CRITICAL",
        title="B0HOME0001 Buy Box seized by competitor",
        detail="Competitor at $81.50 — your price $89.99 (gap 9.4%). Revenue impact est. $420/day",
        asin="B0HOME0001", sku="SKU-HOME-001",
        data={"your_price": 89.99, "competitor_price": 81.50, "gap_pct": 0.094, "est_daily_loss": 420},
        created_at=_ts(2),
    ))

    # ── HIGH alerts → real-time Slack push ──────────────────────────────────
    store.add_alert(AlertRecord(
        alert_type="LOW_INVENTORY",
        severity="HIGH",
        title="B0GADGET002 critically low — 3 units left",
        detail="Fulfillable 3 < threshold 20. At current sales velocity runs out in 1.2 days",
        asin="B0GADGET002", sku="SKU-GADGET-002",
        data={"qty": 3, "threshold": 20, "days_remaining": 1.2},
        created_at=_ts(3),
    ))
    store.add_alert(AlertRecord(
        alert_type="PRICE_CHANGE",
        severity="HIGH",
        title="B0HOME0002 price undercutting — Buy Box at risk",
        detail="Buy Box moved to $21.99 (-12%). Your price $24.99 — not winning Buy Box",
        asin="B0HOME0002", sku="SKU-HOME-002",
        data={"buy_box_price": 21.99, "your_price": 24.99, "drop_pct": 0.12},
        created_at=_ts(4),
    ))

    # ── WARN alerts → daily briefing only ───────────────────────────────────
    store.add_alert(AlertRecord(
        alert_type="LOW_INVENTORY",
        severity="WARN",
        title="B0SPORT001 inventory low — 8 units",
        detail="Fulfillable 8 < threshold 15. Replenishment recommended",
        asin="B0SPORT001", sku="SKU-SPORT-001",
        data={"qty": 8, "threshold": 15},
        created_at=_ts(6),
    ))
    store.add_alert(AlertRecord(
        alert_type="PRICE_CHANGE",
        severity="WARN",
        title="B0GADGET001 baseline price deviation",
        detail="Current price $47.50 vs baseline $49.99 (-5.0%)",
        asin="B0GADGET001", sku="SKU-GADGET-001",
        data={"current": 47.50, "baseline": 49.99, "drop_pct": 0.05},
        created_at=_ts(8),
    ))
    store.add_alert(AlertRecord(
        alert_type="ACOS_SPIKE",
        severity="WARN",
        title="Sponsored Products ACOS rose to 38.2%",
        detail="ACOS 38.2% > target 25% — campaign 'GADGET-SP-AUTO' overbidding",
        asin="B0GADGET001", sku="SKU-GADGET-001",
        data={"acos": 0.382, "target": 0.25, "campaign": "GADGET-SP-AUTO"},
        created_at=_ts(10),
    ))
    store.add_alert(AlertRecord(
        alert_type="CAMPAIGN_BUDGET_EXHAUSTED",
        severity="WARN",
        title="Campaign 'HOME-SP-KW' budget exhausted at 14:00 UTC",
        detail="Daily budget $50 consumed in 14h — missed prime-time traffic",
        asin="B0HOME0001", sku="SKU-HOME-001",
        data={"budget": 50.0, "spent": 50.0, "exhausted_at": "14:00 UTC"},
        created_at=_ts(12),
    ))

    # ── INFO alert (historical) ──────────────────────────────────────────────
    store.add_alert(AlertRecord(
        alert_type="HEALTH_SCORE",
        severity="INFO",
        title="Operations health score: 74/100",
        detail="Order defect rate 0.8% (target <1%), late shipment 2.1% (target <4%)",
        asin="", sku="",
        data={"score": 74, "odr": 0.008, "late_shipment": 0.021, "cancel_rate": 0.006},
        created_at=_ts(24),
    ))

    # One already-slack-notified alert (deduplication demo)
    _notified = AlertRecord(
        alert_type="OUT_OF_STOCK",
        severity="CRITICAL",
        title="B0SPORT002 went out of stock (notified)",
        detail="Fulfillable qty reached 0 — already pushed to Slack",
        asin="B0SPORT002", sku="SKU-SPORT-002",
        data={"qty": 0, "threshold": 10},
        created_at=_ts(5),
        slack_notified_at=_ts(5),  # already notified
    )
    store.add_alert(_notified)
    store.mark_slack_notified(_notified.alert_id, _ts(5))


# ──────────────────────────────────────────────────────────────────────────────
# Scenario B — "crisis": new seller in trouble
# ──────────────────────────────────────────────────────────────────────────────
def _seed_crisis(store: AlertStore) -> None:
    store.upsert_inventory_threshold(InventoryThreshold("SKU-CRISIS-001", "B0CRISIS001", 100))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-CRISIS-002", "B0CRISIS002", 50))
    store.upsert_price_watch(PriceWatch("B0CRISIS001", 19.99, 0.03))
    store.upsert_price_watch(PriceWatch("B0CRISIS002", 39.99, 0.05))
    store.set_replenishment_lead_time("B0CRISIS001", 30)
    store.set_replenishment_lead_time("B0CRISIS002", 45)

    store.add_alert(AlertRecord(
        alert_type="OUT_OF_STOCK", severity="CRITICAL",
        title="B0CRISIS001 OUT OF STOCK — all 3 ASINs suppressed",
        detail="0 fulfillable units. Lead time 30 days. Estimated lost revenue $2,100",
        asin="B0CRISIS001", sku="SKU-CRISIS-001",
        data={"qty": 0, "lead_time_days": 30, "est_lost_revenue": 2100},
        created_at=_ts(0.5),
    ))
    store.add_alert(AlertRecord(
        alert_type="BUY_BOX_LOST", severity="CRITICAL",
        title="B0CRISIS002 Buy Box lost — 3 consecutive days",
        detail="Competitor $35.50 vs your $39.99 (gap 11.2%). Need to reprice or improve metrics",
        asin="B0CRISIS002", sku="SKU-CRISIS-002",
        data={"competitor_price": 35.50, "your_price": 39.99, "gap_pct": 0.112, "days_lost": 3},
        created_at=_ts(1),
    ))
    store.add_alert(AlertRecord(
        alert_type="ACCOUNT_HEALTH", severity="HIGH",
        title="Order defect rate warning — 2.1% (target <1%)",
        detail="3 A-to-Z claims in last 30 days. Account health at risk",
        asin="", sku="",
        data={"odr": 0.021, "target": 0.01, "atoz_claims": 3},
        created_at=_ts(2),
    ))
    store.add_alert(AlertRecord(
        alert_type="LOW_INVENTORY", severity="HIGH",
        title="B0CRISIS002 — 5 units left, 0.8 days remaining",
        detail="At current velocity will stock out before replenishment arrives (45 days away)",
        asin="B0CRISIS002", sku="SKU-CRISIS-002",
        data={"qty": 5, "days_remaining": 0.8, "lead_time_days": 45},
        created_at=_ts(3),
    ))


# ──────────────────────────────────────────────────────────────────────────────
# Scenario C — "growth": scaling seller, ad optimization needed
# ──────────────────────────────────────────────────────────────────────────────
def _seed_growth(store: AlertStore) -> None:
    store.upsert_inventory_threshold(InventoryThreshold("SKU-GROW-001", "B0GROW001", 200))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-GROW-002", "B0GROW002", 150))
    store.upsert_inventory_threshold(InventoryThreshold("SKU-GROW-003", "B0GROW003", 80))
    store.upsert_price_watch(PriceWatch("B0GROW001", 15.99, 0.04))
    store.upsert_price_watch(PriceWatch("B0GROW002", 27.99, 0.05))
    store.set_replenishment_lead_time("B0GROW001", 10)
    store.set_replenishment_lead_time("B0GROW002", 14)
    store.set_replenishment_lead_time("B0GROW003", 21)

    store.add_alert(AlertRecord(
        alert_type="ACOS_SPIKE", severity="HIGH",
        title="ACOS 52% on 'GROW-SP-BROAD' — kill or cut bids",
        detail="Last 7 days: spend $840, sales $1,615. ACOS 52% vs target 28%",
        asin="B0GROW001", sku="SKU-GROW-001",
        data={"acos": 0.52, "target": 0.28, "spend": 840, "sales": 1615, "campaign": "GROW-SP-BROAD"},
        created_at=_ts(2),
    ))
    store.add_alert(AlertRecord(
        alert_type="CAMPAIGN_BUDGET_EXHAUSTED", severity="HIGH",
        title="Top campaign 'GROW-SP-EXACT' exhausted at 09:15 UTC",
        detail="Budget $200/day consumed in 9h. Missing 40% of daily impressions",
        asin="B0GROW002", sku="SKU-GROW-002",
        data={"budget": 200, "spent": 200, "exhausted_at": "09:15 UTC", "missed_impressions_pct": 0.40},
        created_at=_ts(4),
    ))
    store.add_alert(AlertRecord(
        alert_type="LOW_INVENTORY", severity="WARN",
        title="B0GROW003 — 62 units (threshold 80)",
        detail="Velocity 4.2 units/day. Recommend placing PO in 3 days",
        asin="B0GROW003", sku="SKU-GROW-003",
        data={"qty": 62, "threshold": 80, "velocity": 4.2, "po_deadline_days": 3},
        created_at=_ts(8),
    ))
    store.add_alert(AlertRecord(
        alert_type="HEALTH_SCORE", severity="INFO",
        title="Operations health score: 95/100 — excellent",
        detail="ODR 0.2%, late shipment 0.8%, no policy violations",
        asin="", sku="",
        data={"score": 95, "odr": 0.002, "late_shipment": 0.008},
        created_at=_ts(24),
    ))


def seed_demo_briefing_store(store: AlertStore, *, reset: bool = True) -> dict:
    """Backward-compatible wrapper: seeds default scenario into given store."""
    return seed_tenant(store, reset=reset, scenario="default")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo AlertStore(s)")
    parser.add_argument("--multi", action="store_true", help="Seed 3 demo tenants (default/crisis/growth)")
    parser.add_argument("--tenant", default="", help="Seed specific tenant ID (default: reads AMAZON_SELLER_ID env or 'default')")
    parser.add_argument("--scenario", default="default", choices=["default", "crisis", "growth"], help="Scenario to seed")
    args = parser.parse_args()

    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    if args.multi:
        scenarios = [("default", "default"), ("seller_B", "crisis"), ("seller_C", "growth")]
        for tenant_id, scenario in scenarios:
            db_path = str(data_dir / f"alerts_{tenant_id}.db")
            store = AlertStore(db_path=db_path)
            result = seed_tenant(store, reset=True, scenario=scenario)
            print(f"[{tenant_id}] {result}")
        return 0

    # Single tenant
    import os
    if args.tenant:
        tenant_id = args.tenant
    else:
        raw = os.environ.get("AMAZON_SELLER_ID", "").strip()
        import re
        tenant_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw) if raw else "default"

    db_path = str(data_dir / f"alerts_{tenant_id}.db")
    store = AlertStore(db_path=db_path)
    result = seed_tenant(store, reset=True, scenario=args.scenario)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
