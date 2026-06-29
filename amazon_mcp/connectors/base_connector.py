"""BaseConnector — shared OAuth refresh, rate-limit, and dry-run fixture contract.

Concrete connectors (AmazonConnector, MercadoLibreConnector, TikTokConnector)
inherit this class and implement the abstract platform methods.
The briefing engine only calls the abstract interface and never imports
platform-specific clients directly.
"""
from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from amazon_mcp.paths import fixture_path

_LOG = logging.getLogger(__name__)
_FIXTURES_ROOT = fixture_path()


class BaseConnector(ABC):
    """Abstract connector shared across Amazon, Mercado Libre, and TikTok."""

    def __init__(self, *, dry_run: bool = True, cache_ttl: int = 300):
        self.dry_run = dry_run
        self.cache_ttl = cache_ttl
        self._token: str | None = None
        self._token_expiry: float = 0.0

    # ── Token lifecycle ───────────────────────────────────────────────────────

    @abstractmethod
    async def _refresh_token(self) -> tuple[str, float]:
        """Return (access_token, expiry_unix_ts). Called when token expires."""

    async def get_token(self) -> str:
        if self.dry_run:
            return "DRY_RUN_TOKEN"
        now = time.monotonic()
        if not self._token or now >= self._token_expiry - 30:
            token, expiry = await self._refresh_token()
            self._token = token
            self._token_expiry = expiry
        return self._token  # type: ignore[return-value]

    # ── HTTP primitives ───────────────────────────────────────────────────────

    async def _get(self, url: str, params: dict | None = None,
                   headers: dict | None = None) -> dict[str, Any]:
        token = await self.get_token()
        hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, headers=hdrs)
            resp.raise_for_status()
            if resp.status_code == 204:
                return {}
            return resp.json()

    async def _post(self, url: str, body: dict | None = None,
                    headers: dict | None = None) -> dict[str, Any]:
        token = await self.get_token()
        hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=body or {}, headers=hdrs)
            resp.raise_for_status()
            if resp.status_code == 204:
                return {}
            return resp.json()

    # ── Fixture loader ────────────────────────────────────────────────────────

    def _fixture(self, *parts: str) -> dict[str, Any]:
        """Load a JSON fixture file from tests/fixtures/<parts>."""
        path = _FIXTURES_ROOT.joinpath(*parts)
        if not path.exists():
            _LOG.warning("Fixture missing: %s — returning empty dict", path)
            return {}
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    # ── Abstract platform methods ─────────────────────────────────────────────

    @abstractmethod
    async def get_orders_summary(
        self, *, days: int = 7, site_id: str = ""
    ) -> dict[str, Any]:
        """Return normalized order summary for the platform."""

    @abstractmethod
    async def get_inventory(
        self, *, site_id: str = "", skus: list[str] | None = None
    ) -> dict[str, Any]:
        """Return normalized inventory rows."""

    @abstractmethod
    async def get_account_health(self) -> dict[str, Any]:
        """Return platform account health / policy status."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Short identifier: 'amazon' | 'meli' | 'tiktok'."""
