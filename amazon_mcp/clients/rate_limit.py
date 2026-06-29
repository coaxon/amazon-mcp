from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

# SP-API per-category limits (rate = tokens/sec, burst = max bucket).
SP_API_RATE_LIMITS: dict[str, tuple[float, int]] = {
    "orders": (1.0 / 60.0, 1),
    "reports": (1.0 / 45.0, 1),
    "inventory": (2.0, 5),
    "products": (5.0, 10),
    "catalog": (2.0, 5),
    "finances": (0.5, 5),
    "inbound": (2.0, 5),
    "notifications": (1.0, 2),
    "dataKiosk": (0.5, 2),
    "sellers": (1.0, 2),
    "default": (2.0, 5),
}

_PATH_CATEGORY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/orders/", "orders"),
    ("/reports/", "reports"),
    ("/fba/inventory/", "inventory"),
    ("/products/", "products"),
    ("/catalog/", "catalog"),
    ("/finances/", "finances"),
    ("/inbound/", "inbound"),
    ("/notifications/", "notifications"),
    ("/dataKiosk/", "dataKiosk"),
    ("/sellers/", "sellers"),
)


def resolve_sp_endpoint_category(endpoint_key: str) -> str:
    """Map sp_api call_with_backoff keys to limit category."""
    path = endpoint_key
    if path.startswith("sp:POST:"):
        path = path[len("sp:POST:") :]
    elif path.startswith("sp:"):
        path = path[len("sp:") :]
    for prefix, category in _PATH_CATEGORY_PREFIXES:
        if path.startswith(prefix):
            return category
    return "default"


def rate_limit_for_category(category: str) -> tuple[float, int]:
    return SP_API_RATE_LIMITS.get(category, SP_API_RATE_LIMITS["default"])


class RateLimitError(Exception):
    """HTTP 429 or synthetic rate-limit signal."""

    def __init__(self, message: str = "rate limited", *, retry_after: float = 1.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class RateLimitStats:
    requests: int = 0
    throttled: int = 0
    backoff_sleeps: int = 0
    total_backoff_s: float = 0.0


class TokenBucket:
    """Per-endpoint token bucket (proactive pacing)."""

    def __init__(self, rate: float = 2.0, burst: int = 5) -> None:
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            if self._tokens < 1:
                wait = (1 - self._tokens) / self.rate
                await asyncio.sleep(wait)
                self._tokens = 0
                self._last = time.monotonic()
            else:
                self._tokens -= 1


class RateLimitRegistry:
    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self.stats = RateLimitStats()

    def bucket(self, endpoint_key: str) -> TokenBucket:
        category = (
            resolve_sp_endpoint_category(endpoint_key)
            if endpoint_key.startswith("sp:")
            else endpoint_key
        )
        if category not in self._buckets:
            rate, burst = rate_limit_for_category(category)
            self._buckets[category] = TokenBucket(rate=rate, burst=burst)
        return self._buckets[category]

    async def call_with_backoff(
        self,
        endpoint_key: str,
        fn: Callable[[], Awaitable[T]],
        *,
        max_attempts: int = 6,
        base_delay: float = 0.25,
        max_delay: float = 8.0,
    ) -> T:
        """Acquire token, execute fn; on RateLimitError exponential backoff + retry."""
        attempt = 0
        while True:
            attempt += 1
            self.stats.requests += 1
            await self.bucket(endpoint_key).acquire()
            try:
                return await fn()
            except RateLimitError as exc:
                self.stats.throttled += 1
                if attempt >= max_attempts:
                    raise
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                delay = max(delay, exc.retry_after)
                self.stats.backoff_sleeps += 1
                self.stats.total_backoff_s += delay
                await asyncio.sleep(delay)
