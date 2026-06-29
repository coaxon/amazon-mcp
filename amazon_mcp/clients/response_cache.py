from __future__ import annotations

import time
from typing import Any

BRIEFING_CACHE_TTL: dict[str, int] = {
    "inventory": 600,
    "sales_by_asin": 3600,
    "catalog": 900,
    "pricing": 300,
    "default": 300,
}


def briefing_cache_ttl(category: str) -> int:
    return BRIEFING_CACHE_TTL.get(category, BRIEFING_CACHE_TTL["default"])


class ResponseCache:
    """Thread-safe in-process TTL cache for SP/Ads API responses."""

    def __init__(self, ttl_seconds: int = 300, maxsize: int = 2000) -> None:
        self.ttl = ttl_seconds
        self.maxsize = max(1, maxsize)
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        entry = self._store.get(key)
        if entry is None:
            return _MISS
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return _MISS
        return value

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        ttl = self.ttl if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            return
        if len(self._store) >= self.maxsize and key not in self._store:
            oldest = next(iter(self._store))
            del self._store[oldest]
        self._store[key] = (time.monotonic() + ttl, value)

    def invalidate(self, prefix: str = "") -> int:
        if not prefix:
            count = len(self._store)
            self._store.clear()
            return count
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            del self._store[k]
        return len(keys)

    @property
    def size(self) -> int:
        return len(self._store)


_MISS = object()
CACHE_MISS = _MISS
