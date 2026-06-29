"""Bearer API key middleware — per-tenant keys, tenant_id injection, rate limiting."""
from __future__ import annotations

import logging
import os
from typing import Callable
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _global_api_key() -> str:
    """Legacy single shared key from env var (fallback when per-tenant keys not configured)."""
    return os.environ.get("AMAZON_MCP_API_KEY", "").strip()


def redact_webhook_url(url: str) -> str:
    """Redact webhook URLs — expose only scheme+host."""
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.netloc or "unknown-host"
    return f"{parsed.scheme}://{host}/REDACTED"


class McpApiKeyMiddleware(BaseHTTPMiddleware):
    """Multi-mode Bearer auth middleware.

    Priority order:
    1. Per-tenant key lookup (api_key_store) — extracts tenant_id from key record
    2. Global shared key (AMAZON_MCP_API_KEY env) — tenant_id from X-Tenant-ID header or 'default'
    3. No key configured — request passes through (unauthenticated, logged at startup)

    On successful auth, injects X-Tenant-ID into the downstream request scope so
    domain handlers can read params["tenant_id"] without each caller supplying it.
    """

    def __init__(self, app, *, api_key: str = "", mcp_path: str = "/mcp") -> None:
        super().__init__(app)
        self._global_key = api_key
        self._mcp_path = mcp_path.rstrip("/") or "/mcp"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path.rstrip("/") or "/"
        if path != self._mcp_path and not path.startswith(self._mcp_path + "/"):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            if self._global_key or _has_any_tenant_key():
                return _unauthorized("Missing or malformed Authorization header. Use: Authorization: Bearer <key>")
            return await call_next(request)

        raw_key = auth_header[len("Bearer "):]

        # ── Attempt per-tenant key lookup first ──────────────────────────────
        try:
            from amazon_mcp_pro.gateway.api_key_store import check_rate_limit, lookup_key
            record = lookup_key(raw_key)
            if record is not None:
                if not check_rate_limit(record.key_hash, record.rate_limit_rpm):
                    return JSONResponse(
                        {
                            "ok": False,
                            "error": "Rate limit exceeded",
                            "rate_limit_rpm": record.rate_limit_rpm,
                            "hint": "Reduce request frequency or upgrade your plan.",
                        },
                        status_code=429,
                    )
                # Inject tenant_id for downstream handlers
                request.state.tenant_id = record.tenant_id
                return await call_next(request)
        except Exception:
            pass

        # ── Fall back to global shared key ───────────────────────────────────
        import hmac
        if self._global_key:
            expected = f"Bearer {self._global_key}"
            if hmac.compare_digest(auth_header.encode(), expected.encode()):
                tenant_id = request.headers.get("x-tenant-id", "default") or "default"
                request.state.tenant_id = tenant_id
                return await call_next(request)
            return _unauthorized("Invalid API key.")

        # No auth configured at all — pass through (startup logged warning)
        return await call_next(request)


def _unauthorized(hint: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": "Unauthorized", "hint": hint},
        status_code=401,
    )


def _has_any_tenant_key() -> bool:
    try:
        from amazon_mcp_pro.gateway.api_key_store import list_keys
        return len(list_keys()) > 0
    except Exception:
        return False


def install_mcp_api_key_middleware(mcp_instance) -> None:
    api_key = _global_api_key()
    if not api_key:
        try:
            from amazon_mcp_pro.gateway.api_key_store import list_keys
            has_tenant_keys = len(list_keys()) > 0
        except Exception:
            has_tenant_keys = False
        if not has_tenant_keys:
            _log.warning(
                "AMAZON_MCP_API_KEY is not set — /mcp endpoint is unauthenticated; "
                "set the env var or issue tenant keys via amazon_admin(action='issue_key')"
            )

    original = mcp_instance.streamable_http_app

    def _wrapped():
        app = original()
        app.add_middleware(McpApiKeyMiddleware, api_key=api_key)
        return app

    mcp_instance.streamable_http_app = _wrapped  # type: ignore[method-assign]
