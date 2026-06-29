"""Gateway tenant isolation and semantic tool smoke tests."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from amazon_mcp.gateway.router import GatewayRouter
from amazon_mcp.gateway.tenant import TenantContext, TenantRegistry


@pytest.fixture
def isolated_registry(tmp_path: Path) -> TenantRegistry:
    return TenantRegistry(path=tmp_path / "tenants.json")


@pytest.fixture
def router(isolated_registry: TenantRegistry) -> GatewayRouter:
    GatewayRouter.reset_singleton()
    return GatewayRouter(registry=isolated_registry)


def _ctx(tenant_id: str, secret: str = "sec") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        lwa_client_id=f"client-{tenant_id}",
        lwa_client_secret=secret,
        lwa_refresh_token=f"refresh-{tenant_id}",
        dry_run=True,
    )


def test_get_client_returns_isolated_instances(router: GatewayRouter, isolated_registry: TenantRegistry):
    isolated_registry.register(_ctx("tenant-a"))
    isolated_registry.register(_ctx("tenant-b"))
    a = router.get_client("tenant-a")
    b = router.get_client("tenant-b")
    assert a is not b
    assert a.cfg.lwa_client_id == "client-tenant-a"
    assert b.cfg.lwa_client_id == "client-tenant-b"


def test_credentials_not_mixed(router: GatewayRouter, isolated_registry: TenantRegistry):
    isolated_registry.register(_ctx("t1", "secret-one"))
    isolated_registry.register(_ctx("t2", "secret-two"))
    c1 = router.get_client("t1")
    c2 = router.get_client("t2")
    assert c1.auth.client_secret != c2.auth.client_secret


def test_unauthorized_tenant_raises(router: GatewayRouter):
    with pytest.raises(ValueError, match="Unauthorized tenant"):
        router.get_client("unknown-tenant")


def test_tenant_registry_persistence(isolated_registry: TenantRegistry):
    isolated_registry.register(_ctx("persist-me"))
    reloaded = TenantRegistry(path=isolated_registry._path)
    assert reloaded.get("persist-me") is not None
    assert reloaded.get("persist-me").lwa_client_id == "client-persist-me"


def test_invalidate_clears_pool(router: GatewayRouter, isolated_registry: TenantRegistry):
    isolated_registry.register(_ctx("x"))
    first = router.get_client("x")
    router.invalidate("x")
    second = router.get_client("x")
    assert first is not second


@pytest.mark.asyncio
async def test_semantic_tools_dry_run_ok():
    from amazon_mcp.server import (
        competitor_price_alert,
        how_long_inventory_last,
        protect_profit_margin,
    )

    inv = json.loads(await how_long_inventory_last("SKU-POC-001", 2.0))
    assert inv["ok"] is True
    assert inv["urgency"] in ("HIGH", "MEDIUM", "LOW")

    margin = json.loads(await protect_profit_margin("B0POC00001", 0.3))
    assert margin["ok"] is True
    assert margin["action"] in ("RAISE", "LOWER", "OK")

    alert = json.loads(await competitor_price_alert("B0POC00001", 0.05))
    assert alert["ok"] is True
    assert "alert" in alert


def test_list_tenants(router: GatewayRouter, isolated_registry: TenantRegistry):
    isolated_registry.register(_ctx("alpha"))
    isolated_registry.register(_ctx("beta"))
    assert isolated_registry.list_tenants() == ["alpha", "beta"]
