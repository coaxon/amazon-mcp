"""Tests for platform circuit breaker — state machine, trip/reset, admin integration."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")


@pytest.fixture(autouse=True)
def _patch_cb(tmp_path, monkeypatch):
    """Fresh registry + state file per test."""
    import amazon_mcp.gateway.circuit_breaker as cb_mod
    monkeypatch.setattr(cb_mod, "_STATE_FILE", tmp_path / "cb_state.json")
    # Clear breaker registry
    with cb_mod._breakers_lock:
        cb_mod._breakers.clear()
    yield
    with cb_mod._breakers_lock:
        cb_mod._breakers.clear()


@pytest.fixture(autouse=True)
def _ensure_registry():
    import amazon_mcp.server  # noqa: F401
    yield


from amazon_mcp.gateway.circuit_breaker import (
    CBState,
    CircuitBreaker,
    CircuitBreakerOpenError,
    PlatformConfig,
    check_platform,
    get_breaker,
    get_snapshot,
    record_failure,
    record_success,
    reset_breaker,
)
from amazon_mcp.tools.registry import dispatch_domain


def _make_breaker(
    platform: str = "test",
    failure_threshold: int = 3,
    cooldown_seconds: int = 60,
    sample_size: int = 10,
    success_threshold: int = 2,
) -> CircuitBreaker:
    cfg = PlatformConfig(
        platform=platform,
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
        sample_size=sample_size,
        success_threshold=success_threshold,
    )
    return CircuitBreaker(cfg)


# ── CBState transitions ───────────────────────────────────────────────────────

class TestCircuitBreakerState:
    def test_starts_closed(self):
        cb = _make_breaker()
        assert cb.snapshot().state == CBState.CLOSED.value

    def test_trips_to_open_after_threshold(self):
        cb = _make_breaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.snapshot().state == CBState.OPEN.value

    def test_does_not_trip_before_threshold(self):
        cb = _make_breaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.snapshot().state == CBState.CLOSED.value

    def test_success_resets_consecutive_counter(self):
        cb = _make_breaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # reset counter
        cb.record_failure()
        cb.record_failure()  # only 2 consecutive now → still closed
        assert cb.snapshot().state == CBState.CLOSED.value

    def test_manual_reset_to_closed(self):
        cb = _make_breaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.snapshot().state == CBState.OPEN.value
        cb.reset()
        assert cb.snapshot().state == CBState.CLOSED.value
        assert cb.snapshot().consecutive_failures == 0

    def test_is_open_blocks_when_tripped(self):
        cb = _make_breaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open() is True

    def test_is_open_false_when_closed(self):
        cb = _make_breaker()
        assert cb.is_open() is False

    def test_half_open_after_cooldown(self):
        cb = _make_breaker(failure_threshold=2, cooldown_seconds=0)
        cb.record_failure()
        cb.record_failure()
        # With cooldown_seconds=0, immediate half-open transition
        result = cb.is_open()
        assert result is False  # probe allowed
        assert cb.snapshot().state == CBState.HALF_OPEN.value

    def test_half_open_success_closes(self):
        cb = _make_breaker(failure_threshold=2, cooldown_seconds=0, success_threshold=1)
        cb.record_failure()
        cb.record_failure()
        cb.is_open()  # trigger HALF_OPEN
        cb.record_success()
        assert cb.snapshot().state == CBState.CLOSED.value

    def test_half_open_failure_reopens(self):
        cb = _make_breaker(failure_threshold=2, cooldown_seconds=0)
        cb.record_failure()
        cb.record_failure()
        cb.is_open()  # trigger HALF_OPEN
        cb.record_failure()  # probe failed
        assert cb.snapshot().state == CBState.OPEN.value

    def test_error_rate_based_trip(self):
        cb = _make_breaker(failure_threshold=100, sample_size=4)
        # 50% error rate over 4 samples → trip (threshold 0.5)
        cb.record_success()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()  # 2/4 = 50% → trips
        assert cb.snapshot().state == CBState.OPEN.value


# ── CircuitBreakerOpenError ───────────────────────────────────────────────────

class TestCircuitBreakerOpenError:
    def test_to_dict_shape(self):
        err = CircuitBreakerOpenError("meli", 45.5)
        d = err.to_dict()
        assert d["ok"] is False
        assert d["circuit_breaker_open"] is True
        assert d["platform"] == "meli"
        assert d["cooldown_remaining_seconds"] == 45.5
        assert "hint" in d


# ── Snapshot ──────────────────────────────────────────────────────────────────

class TestSnapshot:
    def test_snapshot_fields(self):
        cb = _make_breaker("snap_test")
        snap = cb.snapshot()
        assert snap.platform == "snap_test"
        assert snap.state == CBState.CLOSED.value
        assert snap.total_requests == 0
        assert snap.error_rate_pct == 0.0

    def test_snapshot_after_failures(self):
        cb = _make_breaker()
        cb.record_failure()
        cb.record_failure()
        snap = cb.snapshot()
        assert snap.consecutive_failures == 2
        assert snap.total_failures == 2
        assert snap.error_rate_pct == 100.0

    def test_snapshot_to_dict(self):
        cb = _make_breaker()
        d = cb.snapshot().to_dict()
        assert "state" in d
        assert "error_rate_pct" in d
        assert "sample_window" in d


# ── Module-level helpers ──────────────────────────────────────────────────────

class TestModuleHelpers:
    def test_get_breaker_creates_and_reuses(self):
        b1 = get_breaker("amazon")
        b2 = get_breaker("amazon")
        assert b1 is b2

    def test_check_platform_passes_when_closed(self):
        check_platform("amazon")  # should not raise

    def test_check_platform_raises_when_open(self):
        cb = get_breaker("meli_test_open")
        for _ in range(5):
            cb.record_failure()
        with pytest.raises(CircuitBreakerOpenError) as exc:
            check_platform("meli_test_open")
        assert exc.value.platform == "meli_test_open"

    def test_record_success_and_failure_via_module(self):
        record_failure("test_platform")
        record_success("test_platform")
        snap = get_snapshot("test_platform")
        assert snap["total_requests"] == 2

    def test_reset_breaker_via_module(self):
        for _ in range(5):
            record_failure("amazon")
        result = reset_breaker("amazon")
        assert result["ok"] is True
        assert result["state"] == "CLOSED"


# ── Admin domain integration ──────────────────────────────────────────────────

class TestAdminCircuitBreakerActions:
    @pytest.mark.asyncio
    async def test_circuit_breaker_status_all(self):
        raw = await dispatch_domain("admin", "circuit_breaker_status", {})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert "circuit_breakers" in inner

    @pytest.mark.asyncio
    async def test_circuit_breaker_status_specific_platform(self):
        raw = await dispatch_domain("admin", "circuit_breaker_status", {"platform": "amazon"})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert inner["platform"] == "amazon"
        assert "snapshot" in inner

    @pytest.mark.asyncio
    async def test_trip_and_reset_circuit_breaker(self):
        # Trip
        trip_raw = await dispatch_domain("admin", "trip_circuit_breaker", {"platform": "meli"})
        trip = json.loads(trip_raw)
        assert trip["ok"] is True
        assert trip["data"]["state"] == "OPEN"

        # Reset
        reset_raw = await dispatch_domain("admin", "reset_circuit_breaker", {"platform": "meli"})
        reset = json.loads(reset_raw)
        assert reset["ok"] is True
        assert reset["data"]["state"] == "CLOSED"

    @pytest.mark.asyncio
    async def test_reset_missing_platform(self):
        raw = await dispatch_domain("admin", "reset_circuit_breaker", {})
        data = json.loads(raw)
        assert data.get("ok") is False or data.get("data", {}).get("ok") is False

    @pytest.mark.asyncio
    async def test_trip_missing_platform(self):
        raw = await dispatch_domain("admin", "trip_circuit_breaker", {})
        data = json.loads(raw)
        assert data.get("ok") is False or data.get("data", {}).get("ok") is False

    @pytest.mark.asyncio
    async def test_platform_status_includes_circuit_breakers(self):
        raw = await dispatch_domain("admin", "platform_status", {})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert "circuit_breakers" in inner
        assert inner["features"]["circuit_breaker"] == "per_platform_state_machine"


# ── Connection status shows circuit breaker info ──────────────────────────────

class TestCommandCenterCircuitBreakerStatus:
    @pytest.mark.asyncio
    async def test_connection_status_has_circuit_breakers(self):
        raw = await dispatch_domain("command_center", "connection_status", {})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert "circuit_breakers" in inner
        assert inner["roadmap"]["P4.1"] == "Platform rate-limit + circuit breaker ✅"
