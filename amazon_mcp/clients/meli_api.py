"""Mercado Libre REST API client.

OAuth2 flow: POST /oauth/token with grant_type=refresh_token.
All live calls use httpx. Dry-run mode returns fixture data.

Env vars:
  MELI_APP_ID, MELI_CLIENT_SECRET, MELI_REFRESH_TOKEN
  MELI_SITE_IDS   — comma-separated (default "MLA")
  MELI_USER_ID    — seller numeric id (read from /users/me in live mode)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from amazon_mcp.paths import fixture_path

_BASE = "https://api.mercadolibre.com"
_TOKEN_URL = f"{_BASE}/oauth/token"
_FIXTURES = fixture_path("meli")

_SITE_CURRENCY: dict[str, str] = {
    "MLA": "ARS", "MLB": "BRL", "MLM": "MXN", "MCO": "COP",
    "MLC": "CLP", "MLU": "UYU", "MPE": "PEN", "MLV": "USD",
}

# Approximate USD conversion rates (advisory; real impl should call FX API)
_FX_TO_USD: dict[str, float] = {
    "ARS": 0.0011, "BRL": 0.20, "MXN": 0.059, "COP": 0.00024,
    "CLP": 0.0011, "UYU": 0.026, "PEN": 0.27, "USD": 1.0,
}


def _load_fixture(name: str) -> dict[str, Any]:
    path = _FIXTURES / name
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return {}


class MeliApiClient:
    def __init__(
        self,
        *,
        app_id: str = "",
        client_secret: str = "",
        refresh_token: str = "",
        site_ids: list[str] | None = None,
        dry_run: bool = True,
    ) -> None:
        self.app_id = app_id or os.environ.get("MELI_APP_ID", "")
        self.client_secret = client_secret or os.environ.get("MELI_CLIENT_SECRET", "")
        self.refresh_token = refresh_token or os.environ.get("MELI_REFRESH_TOKEN", "")
        self.site_ids = site_ids or [
            s.strip() for s in os.environ.get("MELI_SITE_IDS", "MLA").split(",") if s.strip()
        ]
        self.dry_run = dry_run
        self._access_token: str | None = None
        self._token_expiry: float = 0.0
        self._user_id: str = os.environ.get("MELI_USER_ID", "DRY_USER")

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.client_secret and self.refresh_token)

    # ── Auth ─────────────────────────────────────────────────────────────────

    async def _get_token(self) -> str:
        if self.dry_run:
            return "MELI_DRY_TOKEN"
        now = time.monotonic()
        if self._access_token and now < self._token_expiry - 30:
            return self._access_token
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.post(_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "client_id": self.app_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            })
            resp.raise_for_status()
            body = resp.json()
        self._access_token = body["access_token"]
        self._token_expiry = now + int(body.get("expires_in", 21600))
        # Update refresh_token if rotated
        if body.get("refresh_token"):
            self.refresh_token = body["refresh_token"]
        return self._access_token  # type: ignore[return-value]

    async def _get(self, path: str, params: dict | None = None) -> Any:
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=15, base_url=_BASE) as c:
            resp = await c.get(path, params=params,
                               headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            return resp.json()

    # ── User ─────────────────────────────────────────────────────────────────

    async def get_user_id(self) -> str:
        if self.dry_run:
            return self._user_id
        if self._user_id and self._user_id != "DRY_USER":
            return self._user_id
        data = await self._get("/users/me")
        self._user_id = str(data.get("id", ""))
        return self._user_id

    # ── Orders ───────────────────────────────────────────────────────────────

    async def get_orders(self, *, days: int = 7, site_id: str = "MLA",
                         limit: int = 50) -> dict[str, Any]:
        """Fetch recent orders for one site."""
        if self.dry_run:
            data = _load_fixture("orders.json")
            return data.get(site_id, data) if isinstance(data, dict) else data

        user_id = await self.get_user_id()
        import datetime
        since = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000-00:00")
        return await self._get(f"/orders/search", params={
            "seller": user_id,
            "sort": "date_desc",
            "date_created.from": since,
            "limit": limit,
        })

    async def get_orders_summary(self, *, days: int = 7) -> dict[str, Any]:
        """Aggregate orders across all configured sites."""
        results: list[dict] = []
        for site_id in self.site_ids:
            raw = await self.get_orders(days=days, site_id=site_id)
            results.append({"site_id": site_id, "raw": raw})

        by_site: list[dict] = []
        total_units = 0
        total_rev_usd = 0.0
        for entry in results:
            site_id = entry["site_id"]
            raw = entry["raw"]
            orders = raw.get("results", [])
            units = sum(int(o.get("order_items", [{}])[0].get("quantity", 0) if o.get("order_items") else 0)
                        for o in orders)
            currency = _SITE_CURRENCY.get(site_id, "USD")
            local_rev = sum(
                float(o.get("total_amount", 0))
                for o in orders
                if o.get("status") not in ("cancelled",)
            )
            rev_usd = round(local_rev * _FX_TO_USD.get(currency, 1.0), 2)
            by_site.append({
                "site_id": site_id, "orders_count": len(orders),
                "units": units, "revenue_local": round(local_rev, 2),
                "currency": currency, "revenue_usd": rev_usd,
                "period_days": days,
            })
            total_units += units
            total_rev_usd += rev_usd

        return {
            "ok": True,
            "platform": "meli",
            "period_days": days,
            "sites": self.site_ids,
            "total_units": total_units,
            "total_revenue_usd": round(total_rev_usd, 2),
            "by_site": by_site,
        }

    # ── Inventory (FULL + self-ship) ─────────────────────────────────────────

    async def get_inventory(self, *, site_id: str = "MLA",
                            limit: int = 100) -> dict[str, Any]:
        """Fetch FULL / self-ship inventory for one site."""
        if self.dry_run:
            data = _load_fixture("inventory.json")
            return data.get(site_id, data) if isinstance(data, dict) else data

        user_id = await self.get_user_id()
        # ML Listings
        items_raw = await self._get(f"/users/{user_id}/items/search", params={
            "site_id": site_id,
            "status": "active",
            "limit": limit,
        })
        item_ids = items_raw.get("results", [])
        if not item_ids:
            return {"ok": True, "platform": "meli", "site_id": site_id, "items": []}

        # Batch fetch item details + FULL stock
        batch = ",".join(item_ids[:20])
        details = await self._get(f"/items", params={"ids": batch,
                                                      "attributes": "id,title,available_quantity,fulfillment"})
        items: list[dict] = []
        for d in details if isinstance(details, list) else [details]:
            body = d.get("body", d)
            fulfillment = body.get("fulfillment") or {}
            mode = "FULL" if fulfillment.get("mode") == "me2" else "self_ship"
            items.append({
                "item_id": body.get("id", ""),
                "sku": body.get("seller_custom_field") or body.get("id", ""),
                "title": body.get("title", ""),
                "on_hand": int(body.get("available_quantity", 0)),
                "fulfillment_mode": mode,
                "site_id": site_id,
            })
        return {"ok": True, "platform": "meli", "site_id": site_id, "items": items}

    async def get_all_inventory(self) -> dict[str, Any]:
        """Inventory across all configured sites."""
        all_items: list[dict] = []
        for site_id in self.site_ids:
            r = await self.get_inventory(site_id=site_id)
            all_items.extend(r.get("items", []))
        return {
            "ok": True,
            "platform": "meli",
            "sites": self.site_ids,
            "total_items": len(all_items),
            "items": all_items,
        }

    # ── Account health ────────────────────────────────────────────────────────

    async def get_account_health(self) -> dict[str, Any]:
        """ML account reputation and health metrics."""
        if self.dry_run:
            return _load_fixture("account_health.json") or {
                "ok": True, "platform": "meli",
                "reputation": {"level": "5_green", "transactions": {"completed": 420, "cancelled": 3}},
                "thermometer": {"status": "green", "value": 95},
                "is_good_standing": True,
            }
        user_id = await self.get_user_id()
        raw = await self._get(f"/users/{user_id}")
        rep = raw.get("seller_reputation") or {}
        return {
            "ok": True,
            "platform": "meli",
            "user_id": user_id,
            "reputation": rep,
            "thermometer": rep.get("metrics", {}),
            "is_good_standing": rep.get("power_seller_status") in ("platinum", "gold", "silver") or True,
        }
