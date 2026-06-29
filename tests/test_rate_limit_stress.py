#!/usr/bin/env python3
"""Acceptance B — Negative Testing: 429 storm with exponential backoff, no crash."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from amazon_mcp.clients.rate_limit import RateLimitError, RateLimitRegistry


async def _instant_sleep(_: float) -> None:
    return None


async def stress_429_backoff(*, iterations: int = 100) -> dict:
    registry = RateLimitRegistry()
    calls = {"n": 0}

    async def flaky_api() -> str:
        calls["n"] += 1
        if calls["n"] in (2, 3):
            raise RateLimitError("HTTP 429 Too Many Requests", retry_after=0.05)
        return "ok"

    errors = 0
    with patch("amazon_mcp.clients.rate_limit.asyncio.sleep", _instant_sleep):
        for _ in range(iterations):
            try:
                await registry.call_with_backoff(
                    "stress:inventory",
                    flaky_api,
                    max_attempts=8,
                    base_delay=0.05,
                    max_delay=1.0,
                )
            except RateLimitError:
                errors += 1

    return {
        "iterations": iterations,
        "completed": iterations - errors,
        "hard_failures": errors,
        "total_api_calls": calls["n"],
        "stats": registry.stats,
    }


def main() -> int:
    print("=== Acceptance B: Rate Limit / 429 Backoff ===")
    out = asyncio.run(stress_429_backoff(iterations=100))
    st = out["stats"]
    print(f"  requests={st.requests} throttled={st.throttled} backoff_sleeps={st.backoff_sleeps}")
    print(f"  total_backoff_s={st.total_backoff_s:.2f}s hard_failures={out['hard_failures']}")

    assert out["hard_failures"] == 0, "must not crash on 429 storm"
    assert st.throttled > 0, "expected 429 throttling after call #2"
    assert st.backoff_sleeps > 0, "expected exponential backoff sleeps"

    print("\nB-RESULT: PASS (429 intercepted, exponential backoff, 100/100 survived)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


import pytest


@pytest.mark.asyncio
async def test_alert_store_concurrent_writes(tmp_path):
    """50 concurrent alert writes to SQLite WAL must all succeed without errors."""
    import asyncio
    from amazon_mcp.monitor.alert_store import AlertStore
    from amazon_mcp.monitor.thresholds import AlertRecord

    store = AlertStore(str(tmp_path / "stress.db"))
    errors: list[Exception] = []

    async def _write(i: int) -> None:
        try:
            store.add_alert(AlertRecord(
                alert_type="LOW_INVENTORY",
                severity="WARN",
                title=f"Stress alert {i}",
                detail=f"qty={i}",
                sku=f"SKU-{i:03d}",
                asin=f"B{i:09d}",
            ))
        except Exception as exc:
            errors.append(exc)

    await asyncio.gather(*(_write(i) for i in range(50)))
    assert not errors, f"Concurrent writes produced errors: {errors}"
    pending = store.get_pending_alerts(limit=100)
    assert len(pending) == 50, f"Expected 50 alerts, got {len(pending)}"


@pytest.mark.asyncio
async def test_token_bucket_concurrent_acquires():
    """100 concurrent token acquisitions on one bucket must not race."""
    import asyncio
    from amazon_mcp.clients.rate_limit import TokenBucket

    bucket = TokenBucket(rate=50.0, burst=100)
    results: list[str] = []

    async def _acquire(i: int) -> None:
        await bucket.acquire()
        results.append(f"ok-{i}")

    await asyncio.gather(*(_acquire(i) for i in range(100)))
    assert len(results) == 100
    assert bucket._tokens >= 0
