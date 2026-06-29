"""Billing skeleton — usage ledger and amazon_billing domain."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from amazon_mcp.gateway.billing import UsageLedger, record_tool_usage, reset_usage_ledger
from amazon_mcp.tools.registry import dispatch_domain, dispatch_legacy


@pytest.fixture
def ledger(tmp_path: Path):
    reset_usage_ledger()
    db = str(tmp_path / "usage.db")
    led = UsageLedger(db_path=db)
    import amazon_mcp.gateway.billing as billing_mod
    billing_mod._ledger = led
    yield led
    reset_usage_ledger()


@pytest.fixture(autouse=True)
def _ensure_registry():
    import amazon_mcp.server  # noqa: F401
    yield


@pytest.mark.asyncio
async def test_dispatch_records_usage_event(ledger: UsageLedger):
    await dispatch_legacy("amazon_health", {}, "default")
    time.sleep(0.15)
    summary = ledger.summary("default", days=1)
    assert summary["total_calls"] >= 1
    names = {row["tool_name"] for row in summary["by_tool"]}
    assert "amazon_health" in names


@pytest.mark.asyncio
async def test_domain_dispatch_records_domain_action(ledger: UsageLedger):
    await dispatch_domain("system", "health", "{}", "default")
    time.sleep(0.15)
    summary = ledger.summary("default", days=1)
    names = {row["tool_name"] for row in summary["by_tool"]}
    assert "system.health" in names


@pytest.mark.asyncio
async def test_billing_usage_summary(ledger: UsageLedger):
    ledger.record("default", "catalog.lookup", 2)
    ledger.record("default", "orders.list", 1)
    raw = await dispatch_domain("billing", "usage_summary", '{"days": 7}', "default")
    env = json.loads(raw)
    assert env["ok"] is True
    data = env["data"]
    assert data["total_units"] >= 3
    assert data["tenant_id"] == "default"


@pytest.mark.asyncio
async def test_billing_check_quota_always_allowed(ledger: UsageLedger):
    raw = await dispatch_domain("billing", "check_quota", '{"tool_name": "catalog.lookup"}', "default")
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["data"]["allowed"] is True


def test_record_tool_usage_skips_billing_domain(ledger: UsageLedger):
    record_tool_usage("default", "billing.usage_summary")
    time.sleep(0.1)
    summary = ledger.summary("default", days=1)
    assert summary["total_calls"] == 0
