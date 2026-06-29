"""TikTok Shop API client (Phase P1 — read-only).

Live auth uses HMAC-SHA256 app signature. Dry-run returns fixture data.

Env vars:
  TIKTOK_APP_KEY, TIKTOK_APP_SECRET, TIKTOK_ACCESS_TOKEN
  TIKTOK_SHOP_CIPHER   — shop identifier token
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from amazon_mcp.paths import fixture_path

_BASE = "https://open-api.tiktokglobalshop.com"
_FIXTURES = fixture_path("tiktok")


def _load_fixture(name: str) -> dict[str, Any]:
    path = _FIXTURES / name
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return {}


def _sign(path: str, params: dict, secret: str) -> str:
    """TikTok HMAC-SHA256 signature (simplified — omit file params)."""
    keys = sorted(k for k in params if k not in ("sign", "access_token"))
    concat = secret + path + "".join(f"{k}{params[k]}" for k in keys) + secret
    return hmac.new(secret.encode(), concat.encode(), hashlib.sha256).hexdigest()


class TikTokApiClient:
    def __init__(
        self,
        *,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        shop_cipher: str = "",
        dry_run: bool = True,
    ) -> None:
        self.app_key = app_key or os.environ.get("TIKTOK_APP_KEY", "")
        self.app_secret = app_secret or os.environ.get("TIKTOK_APP_SECRET", "")
        self.access_token = access_token or os.environ.get("TIKTOK_ACCESS_TOKEN", "")
        self.shop_cipher = shop_cipher or os.environ.get("TIKTOK_SHOP_CIPHER", "")
        self.dry_run = dry_run

    @property
    def configured(self) -> bool:
        return bool(self.app_key and self.app_secret and self.access_token)

    def _build_params(self, path: str, extra: dict) -> dict:
        params = {
            "app_key": self.app_key,
            "timestamp": str(int(time.time())),
            "shop_cipher": self.shop_cipher,
            **extra,
        }
        params["sign"] = _sign(path, params, self.app_secret)
        return params

    async def _get(self, path: str, extra: dict | None = None) -> dict[str, Any]:
        params = self._build_params(path, extra or {})
        async with httpx.AsyncClient(timeout=15, base_url=_BASE) as c:
            resp = await c.get(path, params=params,
                               headers={"x-tts-access-token": self.access_token})
            resp.raise_for_status()
            return resp.json()

    # ── Orders ────────────────────────────────────────────────────────────────

    async def get_orders(self, *, days: int = 7, page_size: int = 50) -> dict[str, Any]:
        if self.dry_run:
            return _load_fixture("orders.json")
        create_time_ge = int(time.time()) - days * 86400
        return await self._get("/order/202309/orders/search", {
            "create_time_ge": str(create_time_ge),
            "create_time_lt": str(int(time.time())),
            "page_size": str(page_size),
        })

    async def get_orders_summary(self, *, days: int = 7) -> dict[str, Any]:
        raw = await self.get_orders(days=days)
        orders = raw.get("orders", raw.get("data", {}).get("orders", []))
        active = [o for o in orders if o.get("status") != "CANCELLED"]
        units = sum(
            sum(int(li.get("quantity", 0)) for li in o.get("line_items", []))
            for o in active
        )
        revenue = sum(float(o.get("total_amount", 0)) for o in active)
        by_sku: dict[str, dict] = {}
        for o in active:
            for li in o.get("line_items", []):
                sku = li.get("seller_sku") or li.get("sku_id", "UNKNOWN")
                row = by_sku.setdefault(sku, {"units": 0, "revenue_usd": 0.0, "product_name": ""})
                row["units"] += int(li.get("quantity", 0))
                row["revenue_usd"] += float(li.get("sale_price", 0)) * int(li.get("quantity", 0))
                row["product_name"] = li.get("product_name", "")
        return {
            "ok": True,
            "platform": "tiktok",
            "period_days": days,
            "site": "US-TTS",
            "total_orders": len(active),
            "total_units": units,
            "total_revenue_usd": round(revenue, 2),
            "by_sku": by_sku,
        }

    # ── Inventory ─────────────────────────────────────────────────────────────

    async def get_inventory(self) -> dict[str, Any]:
        if self.dry_run:
            return _load_fixture("inventory.json")
        return await self._get("/product/202309/products/search", {"page_size": "100"})

    async def get_inventory_summary(self) -> dict[str, Any]:
        raw = await self.get_inventory()
        products = raw.get("products", raw.get("data", {}).get("products", []))
        items: list[dict] = []
        for p in products:
            for sku in p.get("skus", []):
                stock_infos = sku.get("stock_infos", [{}])
                total_stock = sum(int(s.get("available_stock", 0)) for s in stock_infos)
                mode = stock_infos[0].get("warehouse_type", "seller_shipping") if stock_infos else "seller_shipping"
                items.append({
                    "product_id": p.get("product_id", ""),
                    "sku": sku.get("seller_sku") or sku.get("id", ""),
                    "title": p.get("product_name", ""),
                    "on_hand": total_stock,
                    "fulfillment_mode": "FBT" if mode == "FBT" else "self_ship",
                    "site": "US-TTS",
                })
        return {
            "ok": True,
            "platform": "tiktok",
            "site": "US-TTS",
            "total_products": len(products),
            "items": items,
        }
