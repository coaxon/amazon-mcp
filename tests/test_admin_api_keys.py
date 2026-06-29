"""Tests for API key store, rate limiter, and admin domain."""
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
def _patch_key_store(tmp_path, monkeypatch):
    import amazon_mcp.gateway.api_key_store as ks
    monkeypatch.setattr(ks, "_KEY_STORE_FILE", tmp_path / "api_keys.json")
    # Reset rate limiter state
    ks._rate_limiter._windows.clear()
    yield
    ks._rate_limiter._windows.clear()


@pytest.fixture(autouse=True)
def _ensure_registry():
    import amazon_mcp.server  # noqa: F401
    yield


from amazon_mcp.gateway.api_key_store import (
    _RateLimiter,
    _hash_key,
    check_rate_limit,
    get_current_rpm,
    issue_key,
    list_keys,
    lookup_key,
    revoke_key,
)
from amazon_mcp.tools.registry import dispatch_domain


# ── _hash_key ─────────────────────────────────────────────────────────────────

class TestHashKey:
    def test_deterministic(self):
        assert _hash_key("abc") == _hash_key("abc")

    def test_different_inputs_different_hashes(self):
        assert _hash_key("key1") != _hash_key("key2")

    def test_64_hex_chars(self):
        h = _hash_key("some_key")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ── issue_key / lookup_key / revoke_key ───────────────────────────────────────

class TestKeyLifecycle:
    def test_issue_returns_plaintext(self):
        result = issue_key("tenant_a", label="test-key")
        assert result["ok"] is True
        assert result["api_key"].startswith("amcp_")
        assert result["tenant_id"] == "tenant_a"

    def test_lookup_by_plaintext(self):
        r = issue_key("tenant_b")
        rec = lookup_key(r["api_key"])
        assert rec is not None
        assert rec.tenant_id == "tenant_b"
        assert rec.active is True

    def test_lookup_wrong_key_returns_none(self):
        issue_key("tenant_c")
        assert lookup_key("amcp_wrong_key_value") is None

    def test_revoke_deactivates_key(self):
        r = issue_key("tenant_d")
        raw_key = r["api_key"]
        key_hash = _hash_key(raw_key)
        revoke_key(key_hash)
        assert lookup_key(raw_key) is None

    def test_revoke_unknown_key(self):
        result = revoke_key("a" * 64)
        assert result["ok"] is False

    def test_multiple_keys_same_tenant(self):
        issue_key("tenant_e", label="key1")
        issue_key("tenant_e", label="key2")
        keys = list_keys(tenant_id="tenant_e")
        assert len(keys) == 2

    def test_list_keys_no_plaintext(self):
        issue_key("tenant_f")
        keys = list_keys(tenant_id="tenant_f")
        assert len(keys) == 1
        # Should have prefix but not full key
        assert "key_hash_prefix" in keys[0]
        assert keys[0]["key_hash_prefix"].endswith("...")
        assert "api_key" not in keys[0]

    def test_list_keys_tenant_filter(self):
        issue_key("T1")
        issue_key("T2")
        t1_keys = list_keys(tenant_id="T1")
        t2_keys = list_keys(tenant_id="T2")
        assert all(k["tenant_id"] == "T1" for k in t1_keys)
        assert all(k["tenant_id"] == "T2" for k in t2_keys)

    def test_key_includes_rate_limit(self):
        r = issue_key("T1", rate_limit_rpm=30)
        rec = lookup_key(r["api_key"])
        assert rec.rate_limit_rpm == 30


# ── _RateLimiter ──────────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_allows_within_limit(self):
        rl = _RateLimiter()
        for _ in range(5):
            assert rl.is_allowed("key1", limit_rpm=10) is True

    def test_blocks_when_over_limit(self):
        rl = _RateLimiter()
        for _ in range(10):
            rl.is_allowed("key1", limit_rpm=10)
        assert rl.is_allowed("key1", limit_rpm=10) is False

    def test_unlimited_zero_never_blocks(self):
        rl = _RateLimiter()
        for _ in range(1000):
            assert rl.is_allowed("key1", limit_rpm=0) is True

    def test_different_keys_independent(self):
        rl = _RateLimiter()
        for _ in range(5):
            rl.is_allowed("keyA", limit_rpm=5)
        # keyA is exhausted but keyB should still work
        assert rl.is_allowed("keyB", limit_rpm=5) is True

    def test_current_rpm_counts_window(self):
        rl = _RateLimiter()
        for _ in range(3):
            rl.is_allowed("key1", limit_rpm=10)
        assert rl.current_rpm("key1") == 3

    def test_current_rpm_zero_initially(self):
        rl = _RateLimiter()
        assert rl.current_rpm("unknown_key") == 0


# ── check_rate_limit / get_current_rpm (module-level) ────────────────────────

class TestRateLimitModule:
    def test_check_rate_limit_allows(self):
        assert check_rate_limit("test_hash_1", limit_rpm=100) is True

    def test_get_current_rpm_after_calls(self):
        for _ in range(3):
            check_rate_limit("test_hash_2", limit_rpm=100)
        assert get_current_rpm("test_hash_2") == 3


# ── Admin domain via dispatch_domain ─────────────────────────────────────────

class TestAdminDomainTool:
    @pytest.mark.asyncio
    async def test_issue_key(self):
        raw = await dispatch_domain("admin", "issue_key",
                                    {"tenant_id": "default", "label": "test"})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert inner["api_key"].startswith("amcp_")
        assert inner["tenant_id"] == "default"

    @pytest.mark.asyncio
    async def test_list_keys(self):
        await dispatch_domain("admin", "issue_key", {"tenant_id": "default"})
        raw = await dispatch_domain("admin", "list_keys", {"tenant_id": "default"})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert inner["count"] >= 1

    @pytest.mark.asyncio
    async def test_revoke_key_by_prefix(self):
        r_raw = await dispatch_domain("admin", "issue_key",
                                      {"tenant_id": "default", "label": "to-revoke"})
        r = json.loads(r_raw)
        raw_key = r["data"]["api_key"]

        # Get the key hash prefix from list_keys
        list_raw = await dispatch_domain("admin", "list_keys", {"tenant_id": "default"})
        list_data = json.loads(list_raw)
        prefix = list_data["data"]["keys"][0]["key_hash_prefix"].replace("...", "")

        rev_raw = await dispatch_domain("admin", "revoke_key", {"key_hash": prefix})
        rev = json.loads(rev_raw)
        assert rev["ok"] is True
        # Key should now be inactive
        assert lookup_key(raw_key) is None

    @pytest.mark.asyncio
    async def test_revoke_missing_key_hash(self):
        raw = await dispatch_domain("admin", "revoke_key", {})
        data = json.loads(raw)
        assert data.get("ok") is False or data.get("data", {}).get("ok") is False

    @pytest.mark.asyncio
    async def test_platform_status(self):
        raw = await dispatch_domain("admin", "platform_status", {})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert "total_api_keys" in inner
        assert "auth_mode" in inner
        assert inner["features"]["quota_enforcement"] == "enabled"

    @pytest.mark.asyncio
    async def test_rate_limit_status_unknown_key(self):
        raw = await dispatch_domain("admin", "rate_limit_status", {"key_hash": "no_such"})
        data = json.loads(raw)
        assert data.get("ok") is False or data.get("data", {}).get("ok") is False

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        raw = await dispatch_domain("admin", "no_such_action", {})
        data = json.loads(raw)
        assert data["ok"] is False


# ── McpApiKeyMiddleware multi-tenant logic ────────────────────────────────────

class TestMiddlewareTenantExtraction:
    """Unit tests for middleware logic without running a full server."""

    def test_lookup_valid_key_returns_tenant(self):
        r = issue_key("tenant_mw", label="mw-test")
        raw_key = r["api_key"]
        rec = lookup_key(raw_key)
        assert rec is not None
        assert rec.tenant_id == "tenant_mw"

    def test_revoked_key_not_found(self):
        r = issue_key("tenant_rev", label="rev-test")
        raw_key = r["api_key"]
        key_hash = _hash_key(raw_key)
        revoke_key(key_hash)
        rec = lookup_key(raw_key)
        assert rec is None

    def test_rate_limited_key_blocked(self):
        r = issue_key("tenant_rl", rate_limit_rpm=2)
        raw_key = r["api_key"]
        rec = lookup_key(raw_key)
        assert rec is not None
        # Exhaust rate limit
        assert check_rate_limit(rec.key_hash, rec.rate_limit_rpm) is True
        assert check_rate_limit(rec.key_hash, rec.rate_limit_rpm) is True
        assert check_rate_limit(rec.key_hash, rec.rate_limit_rpm) is False
