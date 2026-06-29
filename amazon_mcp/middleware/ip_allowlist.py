"""IP allowlist middleware — CIDR-aware, per-path enforcement."""
from __future__ import annotations

import ipaddress
import logging
import os
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_log = logging.getLogger(__name__)

# AMAZON_MCP_IP_ALLOWLIST=1.2.3.4,10.0.0.0/8,::1
_ENV_VAR = "AMAZON_MCP_IP_ALLOWLIST"


def _parse_allowlist(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            # Bare IP → /32 (IPv4) or /128 (IPv6)
            networks.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            _log.warning("IP allowlist: invalid entry %r — skipping", token)
    return networks


def _client_ip(request: Request) -> str:
    """Extract real client IP — honours X-Forwarded-For if present."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        # First entry is the originating client
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


def _ip_allowed(
    ip_str: str,
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in net for net in networks)


class IpAllowlistMiddleware(BaseHTTPMiddleware):
    """Reject requests whose source IP is not in the configured CIDR allowlist.

    Only applied to `mcp_path` (default `/mcp`).
    If allowlist is empty (env var unset or blank), all IPs are allowed.
    """

    def __init__(
        self,
        app,
        *,
        raw_allowlist: str = "",
        mcp_path: str = "/mcp",
    ) -> None:
        super().__init__(app)
        self._networks = _parse_allowlist(raw_allowlist)
        self._mcp_path = mcp_path.rstrip("/") or "/mcp"
        self._enabled = bool(self._networks)
        if self._enabled:
            _log.info(
                "IP allowlist active (%d range(s)): %s",
                len(self._networks),
                raw_allowlist,
            )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._enabled:
            return await call_next(request)

        path = request.url.path.rstrip("/") or "/"
        if path != self._mcp_path and not path.startswith(self._mcp_path + "/"):
            return await call_next(request)

        ip = _client_ip(request)
        if not _ip_allowed(ip, self._networks):
            _log.warning("IP allowlist: blocked %s", ip)
            return JSONResponse(
                {
                    "ok": False,
                    "error": "Forbidden",
                    "hint": "Your IP is not in the server allowlist. Contact your administrator.",
                },
                status_code=403,
            )

        return await call_next(request)


def install_ip_allowlist_middleware(mcp_instance) -> None:
    raw = os.environ.get(_ENV_VAR, "").strip()
    if not raw:
        return  # no-op when not configured

    original = mcp_instance.streamable_http_app

    def _wrapped():
        app = original()
        app.add_middleware(IpAllowlistMiddleware, raw_allowlist=raw)
        return app

    mcp_instance.streamable_http_app = _wrapped  # type: ignore[method-assign]
