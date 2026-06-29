from __future__ import annotations

import asyncio
import enum
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
_PROACTIVE_REFRESH_S = 300.0  # EXPIRING threshold (seconds)

logger = logging.getLogger(__name__)


class TokenState(enum.Enum):
    FRESH = "FRESH"          # ttl > 300s
    EXPIRING = "EXPIRING"    # 0 < ttl <= 300s
    EXPIRED = "EXPIRED"      # ttl <= 0 or no token   # refresh when < 5 min remaining (per intel P0)
_TOKEN_CACHE_DIR = Path(os.environ.get("AMAZON_MCP_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data"))) / ".runtime"


def _token_cache_path(client_id: str) -> Path:
    key = hashlib.sha256(client_id.encode()).hexdigest()[:12]
    return _TOKEN_CACHE_DIR / f"lwa_token_{key}.json"


class LWAAuth:
    """
    Login with Amazon OAuth2 refresh-token flow.
    - Proactive refresh when < 5 min remaining (prevents mid-request 401)
    - Optional file-based shared cache for multi-process/multi-tool reuse
    """

    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 shared_cache: bool = True) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._shared_cache = shared_cache and bool(client_id)
        self._access_token = ""
        self._expires_at = 0.0
        self._refresh_task: asyncio.Task[None] | None = None
        self._refresh_lock: asyncio.Lock | None = None
        self._cache_path: Path | None = _token_cache_path(client_id) if self._shared_cache else None
        self._load_from_file()

    def _load_from_file(self) -> None:
        if not self._cache_path:
            return
        try:
            data = json.loads(self._cache_path.read_text())
            token = data.get("access_token", "")
            exp = float(data.get("expires_at", 0))
            if token and time.time() < exp - _PROACTIVE_REFRESH_S:
                self._access_token = token
                self._expires_at = exp
        except Exception:
            pass

    def _save_to_file(self) -> None:
        if not self._cache_path:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps({"access_token": self._access_token, "expires_at": self._expires_at})
            )
            os.chmod(self._cache_path, 0o600)
        except Exception:
            pass

    async def get_access_token(self) -> str:
        return await self.ensure_fresh()

    async def _refresh(self) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        self._access_token = str(data.get("access_token") or "")
        self._expires_at = time.time() + float(data.get("expires_in") or 3600)
        if not self._access_token:
            raise RuntimeError("LWA token response missing access_token")
        self._save_to_file()

    @property
    def token_state(self) -> TokenState:
        ttl = self.token_ttl_seconds
        if not self._access_token or ttl <= 0:
            return TokenState.EXPIRED
        if ttl <= _PROACTIVE_REFRESH_S:
            return TokenState.EXPIRING
        return TokenState.FRESH

    def _schedule_proactive_refresh(self) -> None:
        """Background refresh when EXPIRING — does not block callers."""
        if self._refresh_task and not self._refresh_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._refresh_task = loop.create_task(self._refresh_safe())

    async def _refresh_safe(self) -> None:
        try:
            await self._refresh()
        except Exception as exc:
            logger.warning("LWA proactive refresh failed: %s", exc)

    async def ensure_fresh(self) -> str:
        """Return valid token; sync refresh if EXPIRED, async prefetch if EXPIRING."""
        state = self.token_state
        if state == TokenState.FRESH:
            return self._access_token
        if state == TokenState.EXPIRING:
            self._schedule_proactive_refresh()
            return self._access_token
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        async with self._refresh_lock:
            if self.token_state != TokenState.EXPIRED:
                return self._access_token
            await self._refresh()
        return self._access_token

    @property
    def token_ttl_seconds(self) -> float:
        """Remaining token lifetime in seconds."""
        return max(0.0, self._expires_at - time.time())
