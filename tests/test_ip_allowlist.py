"""Tests for IP allowlist middleware."""
from __future__ import annotations

import asyncio
import ipaddress
import os
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Unit: _parse_allowlist ────────────────────────────────────────────────────

class TestParseAllowlist:
    def _parse(self, raw: str):
        from amazon_mcp.middleware.ip_allowlist import _parse_allowlist
        return _parse_allowlist(raw)

    def test_single_ip(self):
        nets = self._parse("1.2.3.4")
        assert len(nets) == 1
        assert ipaddress.ip_address("1.2.3.4") in nets[0]

    def test_cidr_block(self):
        nets = self._parse("10.0.0.0/8")
        assert len(nets) == 1
        assert ipaddress.ip_address("10.99.200.1") in nets[0]

    def test_multiple_entries(self):
        nets = self._parse("1.2.3.4,10.0.0.0/8,192.168.1.0/24")
        assert len(nets) == 3

    def test_empty_string(self):
        nets = self._parse("")
        assert nets == []

    def test_blank_entries_skipped(self):
        nets = self._parse("1.2.3.4,,5.6.7.8")
        assert len(nets) == 2

    def test_invalid_entry_skipped(self):
        nets = self._parse("1.2.3.4,not-an-ip,5.6.7.8")
        assert len(nets) == 2

    def test_ipv6_loopback(self):
        nets = self._parse("::1")
        assert len(nets) == 1
        assert ipaddress.ip_address("::1") in nets[0]

    def test_ipv6_cidr(self):
        nets = self._parse("2001:db8::/32")
        assert len(nets) == 1
        assert ipaddress.ip_address("2001:db8::1") in nets[0]

    def test_whitespace_trimmed(self):
        nets = self._parse("  1.2.3.4 ,  10.0.0.0/8  ")
        assert len(nets) == 2


# ── Unit: _ip_allowed ─────────────────────────────────────────────────────────

class TestIpAllowed:
    def _allowed(self, ip: str, raw: str) -> bool:
        from amazon_mcp.middleware.ip_allowlist import _parse_allowlist, _ip_allowed
        return _ip_allowed(ip, _parse_allowlist(raw))

    def test_exact_ip_allowed(self):
        assert self._allowed("1.2.3.4", "1.2.3.4") is True

    def test_other_ip_blocked(self):
        assert self._allowed("1.2.3.5", "1.2.3.4") is False

    def test_cidr_member_allowed(self):
        assert self._allowed("10.99.1.200", "10.0.0.0/8") is True

    def test_cidr_non_member_blocked(self):
        assert self._allowed("172.16.0.1", "10.0.0.0/8") is False

    def test_loopback_in_list(self):
        assert self._allowed("127.0.0.1", "127.0.0.0/8") is True

    def test_multiple_ranges_match_second(self):
        assert self._allowed("192.168.1.50", "10.0.0.0/8,192.168.1.0/24") is True

    def test_ipv6_localhost_allowed(self):
        assert self._allowed("::1", "::1") is True

    def test_malformed_ip_returns_false(self):
        assert self._allowed("not-an-ip", "1.2.3.4") is False

    def test_empty_allowlist_blocks_all(self):
        assert self._allowed("1.2.3.4", "") is False


# ── Unit: _client_ip ─────────────────────────────────────────────────────────

class TestClientIp:
    def test_direct_client(self):
        from amazon_mcp.middleware.ip_allowlist import _client_ip
        req = MagicMock()
        req.headers = {}
        req.client.host = "5.6.7.8"
        assert _client_ip(req) == "5.6.7.8"

    def test_forwarded_for_single(self):
        from amazon_mcp.middleware.ip_allowlist import _client_ip
        req = MagicMock()
        req.headers = {"x-forwarded-for": "1.1.1.1"}
        req.client.host = "proxy.internal"
        assert _client_ip(req) == "1.1.1.1"

    def test_forwarded_for_chain(self):
        from amazon_mcp.middleware.ip_allowlist import _client_ip
        req = MagicMock()
        req.headers = {"x-forwarded-for": "1.1.1.1, 2.2.2.2, 3.3.3.3"}
        req.client.host = "proxy.internal"
        assert _client_ip(req) == "1.1.1.1"

    def test_no_client_returns_default(self):
        from amazon_mcp.middleware.ip_allowlist import _client_ip
        req = MagicMock()
        req.headers = {}
        req.client = None
        assert _client_ip(req) == "0.0.0.0"


# ── Middleware integration ────────────────────────────────────────────────────

class TestIpAllowlistMiddleware:
    def _make_middleware(self, raw_allowlist: str, mcp_path: str = "/mcp"):
        from amazon_mcp.middleware.ip_allowlist import IpAllowlistMiddleware
        app = AsyncMock()
        mw = IpAllowlistMiddleware(app, raw_allowlist=raw_allowlist, mcp_path=mcp_path)
        return mw

    def _make_request(self, path: str, ip: str, forwarded: str = "") -> MagicMock:
        req = MagicMock()
        req.url.path = path
        req.client.host = ip
        headers = {}
        if forwarded:
            headers["x-forwarded-for"] = forwarded
        req.headers = headers
        return req

    def test_disabled_when_empty(self):
        mw = self._make_middleware("")
        assert mw._enabled is False

    def test_enabled_when_configured(self):
        mw = self._make_middleware("1.2.3.4")
        assert mw._enabled is True

    def test_allowed_ip_passes(self):
        mw = self._make_middleware("1.2.3.4")
        req = self._make_request("/mcp", "1.2.3.4")
        next_fn = AsyncMock(return_value=MagicMock(status_code=200))

        async def _run():
            return await mw.dispatch(req, next_fn)

        result = asyncio.run(_run())
        next_fn.assert_called_once()

    def test_blocked_ip_returns_403(self):
        from amazon_mcp.middleware.ip_allowlist import IpAllowlistMiddleware
        from starlette.responses import JSONResponse

        mw = self._make_middleware("1.2.3.4")
        req = self._make_request("/mcp", "9.9.9.9")
        next_fn = AsyncMock()

        async def _run():
            return await mw.dispatch(req, next_fn)

        result = asyncio.run(_run())
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403
        next_fn.assert_not_called()

    def test_non_mcp_path_bypasses_check(self):
        mw = self._make_middleware("1.2.3.4")
        req = self._make_request("/health", "9.9.9.9")
        next_fn = AsyncMock(return_value=MagicMock(status_code=200))

        async def _run():
            return await mw.dispatch(req, next_fn)

        asyncio.run(_run())
        next_fn.assert_called_once()

    def test_disabled_allows_any_ip(self):
        mw = self._make_middleware("")
        req = self._make_request("/mcp", "9.9.9.9")
        next_fn = AsyncMock(return_value=MagicMock(status_code=200))

        async def _run():
            return await mw.dispatch(req, next_fn)

        asyncio.run(_run())
        next_fn.assert_called_once()

    def test_cidr_range_allows_member(self):
        mw = self._make_middleware("10.0.0.0/8")
        req = self._make_request("/mcp", "10.55.1.200")
        next_fn = AsyncMock(return_value=MagicMock(status_code=200))

        async def _run():
            return await mw.dispatch(req, next_fn)

        asyncio.run(_run())
        next_fn.assert_called_once()

    def test_forwarded_for_used_for_check(self):
        mw = self._make_middleware("1.2.3.4")
        req = self._make_request("/mcp", "10.0.0.1", forwarded="1.2.3.4")
        next_fn = AsyncMock(return_value=MagicMock(status_code=200))

        async def _run():
            return await mw.dispatch(req, next_fn)

        asyncio.run(_run())
        next_fn.assert_called_once()

    def test_403_body_has_hint(self):
        import json
        mw = self._make_middleware("1.2.3.4")
        req = self._make_request("/mcp", "9.9.9.9")
        next_fn = AsyncMock()

        async def _run():
            return await mw.dispatch(req, next_fn)

        result = asyncio.run(_run())
        body = json.loads(result.body)
        assert body["ok"] is False
        assert "hint" in body

    def test_mcp_sub_path_also_checked(self):
        from starlette.responses import JSONResponse
        mw = self._make_middleware("1.2.3.4")
        req = self._make_request("/mcp/tools/list", "9.9.9.9")
        next_fn = AsyncMock()

        async def _run():
            return await mw.dispatch(req, next_fn)

        result = asyncio.run(_run())
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403


# ── install_ip_allowlist_middleware ───────────────────────────────────────────

class TestInstallIpAllowlistMiddleware:
    def test_no_op_when_env_empty(self, monkeypatch):
        monkeypatch.delenv("AMAZON_MCP_IP_ALLOWLIST", raising=False)
        from amazon_mcp.middleware.ip_allowlist import install_ip_allowlist_middleware
        mcp_mock = MagicMock()
        original = mcp_mock.streamable_http_app
        install_ip_allowlist_middleware(mcp_mock)
        assert mcp_mock.streamable_http_app == original

    def test_wraps_when_env_set(self, monkeypatch):
        monkeypatch.setenv("AMAZON_MCP_IP_ALLOWLIST", "1.2.3.4")
        from amazon_mcp.middleware.ip_allowlist import install_ip_allowlist_middleware
        mcp_mock = MagicMock()
        original = mcp_mock.streamable_http_app
        install_ip_allowlist_middleware(mcp_mock)
        assert mcp_mock.streamable_http_app != original
