"""B7 GatewayRouter tenant routing through ToolDeps."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from amazon_mcp.gateway.router import GatewayRouter
from amazon_mcp.gateway.tenant import TenantContext, TenantRegistry
from amazon_mcp.tools.registry import dispatch_domain, dispatch_legacy


@pytest.fixture(autouse=True)
def _restore_router():
    yield
    GatewayRouter.reset_singleton()
    import amazon_mcp.server as srv
    srv._reset_ctx_cache()
    srv._ensure_default_tenant()


@pytest.fixture
def isolated_registry(tmp_path: Path) -> TenantRegistry:
    return TenantRegistry(path=tmp_path / "tenants.json")


@pytest.fixture
def router(isolated_registry: TenantRegistry) -> GatewayRouter:
    GatewayRouter.reset_singleton()
    return GatewayRouter(registry=isolated_registry)


def _tenant(tenant_id: str, *, secret: str = "sec", seller: str = "") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        lwa_client_id=f"client-{tenant_id}",
        lwa_client_secret=secret,
        lwa_refresh_token=f"refresh-{tenant_id}",
        seller_id=seller or f"seller-{tenant_id}",
        dry_run=True,
    )


def _wire_deps(router: GatewayRouter, tmp_path: Path) -> None:
    import amazon_mcp.server as srv
    from amazon_mcp.tools.deps import ToolDeps, set_tool_deps

    GatewayRouter._instance = router
    srv._reset_ctx_cache()

    def _store(tenant_id: str = "default"):
        base = tmp_path / "stores" / tenant_id
        base.mkdir(parents=True, exist_ok=True)
        from amazon_mcp.monitor.alert_store import AlertStore
        return AlertStore(db_path=str(base / "alerts.db"))

    def _cogs(tenant_id: str = "default"):
        base = tmp_path / "stores" / tenant_id
        base.mkdir(parents=True, exist_ok=True)
        from amazon_mcp.cogs.store import CogsStore
        return CogsStore(db_path=str(base / "cogs.db"))

    async def _sp_call(coro, tool: str = ""):
        return await srv._sp(coro, tool=tool)

    set_tool_deps(ToolDeps(
        ctx=srv._ctx_for_tenant,
        sp_call=_sp_call,
        json_dumps=srv._json,
        last_ctx_hit=lambda: srv._last_ctx_hit,
        registered_tool_names=srv._registered_tool_names,
        server_start_time=srv._server_start_time,
        alert_engine_getter=lambda: None,
        get_store=_store,
        get_cogs_store=_cogs,
        ensure_default_tenant=lambda: None,
        version="test",
        scoring_version="v1",
    ))


@pytest.mark.asyncio
async def test_default_tenant_health_unchanged(router, isolated_registry, tmp_path):
    isolated_registry.register(_tenant("default"))
    _wire_deps(router, tmp_path)
    raw = await dispatch_legacy("amazon_health", {}, "default")
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["dry_run"] is True
    assert data["service"] == "amazon-mcp"


@pytest.mark.asyncio
async def test_second_tenant_routes_credentials_and_store(router, isolated_registry, tmp_path):
    isolated_registry.register(_tenant("default", secret="default-secret"))
    isolated_registry.register(_tenant("tenant-b", secret="tenant-b-secret"))
    _wire_deps(router, tmp_path)

    cfg_a, sp_a, _ = router.resolve("default")
    cfg_b, sp_b, _ = router.resolve("tenant-b")
    assert sp_a.cfg.lwa_client_id == "client-default"
    assert sp_b.cfg.lwa_client_id == "client-tenant-b"
    assert sp_a is not sp_b

    await dispatch_legacy("import_cogs", {"csv_content": "asin,cogs\nB0TENB01,9.99\n"}, "tenant-b")
    listed = json.loads(await dispatch_legacy("get_cogs", {}, "tenant-b"))
    assert listed["ok"] is True
    assert listed["count"] == 1

    default_list = json.loads(await dispatch_legacy("get_cogs", {}, "default"))
    assert default_list.get("count", 0) == 0


@pytest.mark.asyncio
async def test_unknown_tenant_returns_error(router, isolated_registry, tmp_path):
    isolated_registry.register(_tenant("default"))
    _wire_deps(router, tmp_path)
    raw = await dispatch_domain("catalog", "lookup", '{"asin": "B0POC00001"}', "missing-tenant")
    env = json.loads(raw)
    assert env["ok"] is False
    assert "Unauthorized tenant" in env["data"].get("error", "")


@pytest.mark.asyncio
async def test_consolidated_tool_tenant_id_in_meta(router, isolated_registry, tmp_path):
    isolated_registry.register(_tenant("default"))
    _wire_deps(router, tmp_path)
    raw = await dispatch_domain("system", "health", "{}", "default")
    env = json.loads(raw)
    assert env["ok"] is True
    assert env["meta"]["tenant_id"] == "default"
