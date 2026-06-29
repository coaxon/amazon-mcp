"""Alert threshold models."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid


@dataclass
class InventoryThreshold:
    sku: str
    asin: str
    min_qty: int               # alert when fulfillableQuantity < min_qty
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class PriceWatch:
    asin: str
    baseline_price: float      # price at time of watch setup
    alert_pct: float           # alert when change >= alert_pct (e.g. 0.05 = 5%)
    direction: str = "any"     # "up" | "down" | "any"
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AlertRecord:
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    alert_type: str = ""       # "LOW_INVENTORY" | "PRICE_CHANGE" | "OUT_OF_STOCK" | "BUY_BOX_LOST"
    severity: str = "WARN"     # "INFO" | "WARN" | "CRITICAL"
    title: str = ""
    detail: str = ""
    asin: str = ""
    sku: str = ""
    data: dict = field(default_factory=dict)
    dismissed: bool = False
    slack_notified_at: str = ""  # set when pushed as real-time Slack alert
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
