"""Normalized cross-platform data model.

All connectors produce PlatformSnapshot so the briefing engine never
imports SP-API or ML types directly.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InventoryRow:
    sku: str
    item_id: str          # ASIN (Amazon) or item_id (ML) or tiktok_product_id
    title: str
    on_hand: int
    fulfillment_mode: str  # FBA | FULL | self_ship | FBT
    site_id: str           # ATVPDKIKX0DER | MLA | MLB | US-TTS …
    days_of_cover: float | None = None
    low_stock: bool = False
    reorder_signal: str = ""   # "" | WATCH | URGENT | CRITICAL


@dataclass
class OrderSummaryRow:
    site_id: str
    units: int
    revenue_usd: float
    currency: str
    period_days: int


@dataclass
class PlatformSnapshot:
    platform: str              # "amazon" | "meli" | "tiktok"
    sites: list[str]           # e.g. ["ATVPDKIKX0DER"] or ["MLA","MLB"]
    orders: list[OrderSummaryRow] = field(default_factory=list)
    inventory: list[InventoryRow] = field(default_factory=list)
    listing_count: int = 0
    as_of: str = ""

    def __post_init__(self) -> None:
        if not self.as_of:
            self.as_of = time.strftime("%Y-%m-%d")

    @property
    def total_units(self) -> int:
        return sum(o.units for o in self.orders)

    @property
    def total_revenue_usd(self) -> float:
        return round(sum(o.revenue_usd for o in self.orders), 2)

    @property
    def low_stock_skus(self) -> list[str]:
        return [r.sku for r in self.inventory if r.low_stock]

    def to_briefing_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "sites": self.sites,
            "as_of": self.as_of,
            "orders": {
                "total_units": self.total_units,
                "total_revenue_usd": self.total_revenue_usd,
                "by_site": [
                    {"site_id": o.site_id, "units": o.units,
                     "revenue_usd": o.revenue_usd, "currency": o.currency,
                     "period_days": o.period_days}
                    for o in self.orders
                ],
            },
            "inventory": {
                "listing_count": self.listing_count,
                "on_hand_total": sum(r.on_hand for r in self.inventory),
                "low_stock_count": len(self.low_stock_skus),
                "low_stock_skus": self.low_stock_skus[:10],
                "items": [
                    {"sku": r.sku, "item_id": r.item_id, "title": r.title,
                     "on_hand": r.on_hand, "fulfillment_mode": r.fulfillment_mode,
                     "site_id": r.site_id, "days_of_cover": r.days_of_cover,
                     "low_stock": r.low_stock, "reorder_signal": r.reorder_signal}
                    for r in self.inventory[:50]
                ],
            },
        }
