"""Tests for real quota enforcement (Phase E)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")


@pytest.fixture(autouse=True)
def _patch_billing(tmp_path, monkeypatch):
    """Each test gets an isolated in-memory ledger + quota config."""
    import amazon_mcp.gateway.billing as billing_mod

    monkeypatch.setattr(billing_mod, "_QUOTA_CONFIG_FILE", tmp_path / "quota_config.json")
    # Fresh ledger with in-memory db
    db = str(tmp_path / "test_ledger.db")
    monkeypatch.setattr(billing_mod, "_ledger", None)
    monkeypatch.setenv("AMAZON_USAGE_LEDGER_DB", db)
    billing_mod.reset_usage_ledger()
    yield
    billing_mod.reset_usage_ledger()


@pytest.fixture(autouse=True)
def _ensure_registry():
    import amazon_mcp.server  # noqa: F401
    yield


from amazon_mcp.gateway.billing import (
    QuotaExceededError,
    get_usage_ledger,
    get_tenant_monthly_limit,
    set_tenant_quota,
)
from amazon_mcp.tools.registry import dispatch_domain


# ── UsageLedger.month_usage ───────────────────────────────────────────────────

class TestMonthUsage:
    def test_zero_initially(self):
        assert get_usage_ledger().month_usage("T1") == 0

    def test_records_accumulate(self):
        ledger = get_usage_ledger()
        ledger.record("T1", "orders.list", 1)
        ledger.record("T1", "orders.list", 1)
        assert ledger.month_usage("T1") == 2

    def test_different_tenants_isolated(self):
        ledger = get_usage_ledger()
        ledger.record("TA", "orders.list", 3)
        ledger.record("TB", "orders.list", 7)
        assert ledger.month_usage("TA") == 3
        assert ledger.month_usage("TB") == 7


# ── get/set_tenant_monthly_limit ──────────────────────────────────────────────

class TestQuotaConfig:
    def test_default_limit_all_tier_is_unlimited(self):
        # "all" tier = 0 = unlimited
        limit = get_tenant_monthly_limit("some_unknown_tenant")
        assert limit == 0

    def test_set_and_get_override(self):
        set_tenant_quota("T1", 100)
        assert get_tenant_monthly_limit("T1") == 100

    def test_override_zero_is_unlimited(self):
        set_tenant_quota("T1", 0)
        assert get_tenant_monthly_limit("T1") == 0


# ── UsageLedger.check_quota ───────────────────────────────────────────────────

class TestCheckQuota:
    def test_unlimited_tenant_always_allowed(self):
        result = get_usage_ledger().check_quota("T_unlimited")
        assert result["ok"] is True
        assert result["allowed"] is True
        assert result["monthly_limit"] == 0

    def test_within_quota(self):
        set_tenant_quota("T1", 100)
        get_usage_ledger().record("T1", "orders.list", 5)
        result = get_usage_ledger().check_quota("T1")
        assert result["allowed"] is True
        assert result["monthly_calls_used"] == 5
        assert result["monthly_remaining"] == 95

    def test_at_limit_blocked(self):
        set_tenant_quota("T1", 5)
        for _ in range(5):
            get_usage_ledger().record("T1", "orders.list")
        result = get_usage_ledger().check_quota("T1")
        assert result["allowed"] is False
        assert result["reason"] == "quota exceeded"

    def test_percentage_computed(self):
        set_tenant_quota("T1", 100)
        get_usage_ledger().record("T1", "ads.campaign_list", 30)
        result = get_usage_ledger().check_quota("T1")
        assert result["quota_pct_used"] == 30.0


# ── UsageLedger.enforce_quota ─────────────────────────────────────────────────

class TestEnforceQuota:
    def test_raises_when_over_limit(self):
        set_tenant_quota("T1", 3)
        for _ in range(3):
            get_usage_ledger().record("T1", "orders.list")
        with pytest.raises(QuotaExceededError) as exc_info:
            get_usage_ledger().enforce_quota("T1", "orders.list")
        assert exc_info.value.used == 3
        assert exc_info.value.limit == 3

    def test_does_not_raise_within_limit(self):
        set_tenant_quota("T1", 100)
        get_usage_ledger().record("T1", "orders.list", 50)
        get_usage_ledger().enforce_quota("T1", "orders.list")  # should not raise

    def test_unlimited_never_raises(self):
        set_tenant_quota("T1", 0)  # unlimited
        for _ in range(100):
            get_usage_ledger().record("T1", "orders.list")
        get_usage_ledger().enforce_quota("T1", "orders.list")  # should not raise

    def test_exempt_domains_never_raise(self):
        set_tenant_quota("T1", 1)
        get_usage_ledger().record("T1", "billing.check_quota", 99)
        get_usage_ledger().enforce_quota("T1", tool_name="billing.check_quota")  # exempt
        get_usage_ledger().enforce_quota("T1", tool_name="system.health")
        get_usage_ledger().enforce_quota("T1", tool_name="features.list_all")


# ── QuotaExceededError ────────────────────────────────────────────────────────

class TestQuotaExceededError:
    def test_to_dict_shape(self):
        err = QuotaExceededError("T1", 5000, 5000)
        d = err.to_dict()
        assert d["ok"] is False
        assert d["quota_exceeded"] is True
        assert d["tenant_id"] == "T1"
        assert d["monthly_calls_used"] == 5000
        assert d["monthly_limit"] == 5000
        assert "upgrade_hint" in d


# ── invoke() quota enforcement (end-to-end through registry) ─────────────────

class TestRegistryQuotaGate:
    @pytest.mark.asyncio
    async def test_over_quota_returns_quota_exceeded(self):
        # Use "default" tenant (always registered); set a tiny limit and exhaust it
        set_tenant_quota("default", 2)
        for _ in range(2):
            get_usage_ledger().record("default", "orders.list")
        raw = await dispatch_domain("orders", "revenue_summary", {"tenant_id": "default", "days": 7})
        data = json.loads(raw)
        # Either the envelope ok=False, or inner data has quota_exceeded
        assert data.get("ok") is False or data.get("data", {}).get("quota_exceeded") is True

    @pytest.mark.asyncio
    async def test_within_quota_passes_through(self):
        set_tenant_quota("default", 1000)
        raw = await dispatch_domain("orders", "revenue_summary", {"tenant_id": "default", "days": 7})
        data = json.loads(raw)
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_billing_domain_exempt_from_quota(self):
        set_tenant_quota("default", 0)
        raw = await dispatch_domain("billing", "check_quota", {"tenant_id": "default"})
        data = json.loads(raw)
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_system_domain_exempt_from_quota(self):
        # Exhaust quota, then system.health should still work
        set_tenant_quota("default", 1)
        get_usage_ledger().record("default", "orders.list", 999)
        raw = await dispatch_domain("system", "health", {"tenant_id": "default"})
        data = json.loads(raw)
        assert data["ok"] is True


# ── Billing domain tools ──────────────────────────────────────────────────────

class TestBillingDomainTools:
    @pytest.mark.asyncio
    async def test_usage_summary_includes_quota(self):
        set_tenant_quota("default", 500)
        get_usage_ledger().record("default", "orders.list", 10)
        raw = await dispatch_domain("billing", "usage_summary", {"tenant_id": "default"})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert "monthly_limit" in inner
        assert "monthly_calls_used" in inner
        assert inner["monthly_limit"] == 500

    @pytest.mark.asyncio
    async def test_set_quota_action(self):
        raw = await dispatch_domain("billing", "set_quota",
                                    {"tenant_id": "default", "monthly_limit": 750})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert inner["monthly_limit"] == 750

    @pytest.mark.asyncio
    async def test_set_quota_missing_param(self):
        raw = await dispatch_domain("billing", "set_quota", {"tenant_id": "default"})
        data = json.loads(raw)
        assert data.get("ok") is False or data.get("data", {}).get("ok") is False

    @pytest.mark.asyncio
    async def test_tier_limits_action(self):
        raw = await dispatch_domain("billing", "tier_limits", {})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert "starter" in inner["tier_limits"]
        assert "global_suite" in inner["tier_limits"]

    @pytest.mark.asyncio
    async def test_month_usage_action(self):
        set_tenant_quota("default", 200)
        get_usage_ledger().record("default", "ads.campaign_list", 15)
        raw = await dispatch_domain("billing", "month_usage", {"tenant_id": "default"})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert inner["month_calls_used"] == 15
        assert inner["monthly_limit"] == 200
        assert inner["status"] == "within_quota"

    @pytest.mark.asyncio
    async def test_month_usage_over_quota_status(self):
        set_tenant_quota("default", 5)
        for _ in range(6):
            get_usage_ledger().record("default", "orders.list")
        raw = await dispatch_domain("billing", "month_usage", {"tenant_id": "default"})
        data = json.loads(raw)
        inner = data["data"]
        assert inner["status"] == "over_quota"
