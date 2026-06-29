"""Bearer API key middleware for /mcp streamable-http."""
from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from amazon_mcp.middleware.api_key_auth import McpApiKeyMiddleware, redact_webhook_url
def test_redact_webhook_url():
    url = "https://hooks.slack.com/services/T00/B00/xxxxx"
    assert "REDACTED" in redact_webhook_url(url)
    assert url not in redact_webhook_url(url)


def _mcp_app_with_key(key: str = "test-secret-key"):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def mcp_handler(_):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/mcp", mcp_handler)])
    app.add_middleware(McpApiKeyMiddleware, api_key=key)
    return TestClient(app)


def test_mcp_without_bearer_returns_401():
    client = _mcp_app_with_key()
    resp = client.get("/mcp")
    assert resp.status_code == 401
    assert resp.json().get("error") == "Unauthorized"


def test_mcp_with_wrong_bearer_returns_401():
    client = _mcp_app_with_key()
    resp = client.get("/mcp", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_mcp_with_valid_bearer_not_401():
    client = _mcp_app_with_key()
    resp = client.get("/mcp", headers={"Authorization": "Bearer test-secret-key"})
    assert resp.status_code == 200


def test_middleware_skips_non_mcp_paths():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def home(_):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", home)])
    app.add_middleware(McpApiKeyMiddleware, api_key="secret")
    client = TestClient(app)
    assert client.get("/").status_code == 200
