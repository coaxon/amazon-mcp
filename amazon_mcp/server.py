from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("amazon_mcp.server")

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import FileResponse, Response

from amazon_mcp.auth.lwa import LWAAuth
from amazon_mcp.clients.ads_api import AdsAPIClient
from amazon_mcp.clients.rate_limit import RateLimitRegistry
from amazon_mcp.clients.sp_api import SPAPIClient
from amazon_mcp.config import AmazonConfig
from amazon_mcp.middleware.api_key_auth import install_mcp_api_key_middleware, redact_webhook_url
from amazon_mcp.middleware.ip_allowlist import install_ip_allowlist_middleware
from amazon_mcp.monitor.alert_store import AlertStore, get_default_alert_db_path
from amazon_mcp.paths import data_path
from amazon_mcp.pro_edition import has_pro, pro_required_scenario
from amazon_mcp.tools.bootstrap import init_tool_registry
from amazon_mcp.tools.domain_tools import register_domain_tools, EXPORTS as _DOMAIN_TOOL_EXPORTS
from amazon_mcp.cogs.store import CogsStore, get_default_cogs_db_path
from amazon_mcp.dag.executor import DagExecutor
from amazon_mcp.dag.fast_forward import FastForward

load_dotenv()

from contextlib import asynccontextmanager

# ── Multi-tenant alert store cache (keyed by seller_id → db_path) ────────────
_store_cache: dict[str, AlertStore] = {}
_cogs_store_cache: dict[str, CogsStore] = {}
# Test seam: monkeypatch.setattr(srv, "_alert_store", temp_store) overrides tenant routing.
_alert_store: AlertStore | None = None
_alert_engine: Any | None = None
_daily_briefing_scheduler: Any | None = None
_slack_interaction_handler: Any | None = None
_last_ctx_hit_box: dict[str, bool] = {"value": False}


def _get_store(tenant_id: str = "default") -> AlertStore:
    """Return tenant-scoped AlertStore (default uses env/seller routing)."""
    global _alert_store
    tid = (tenant_id or "default").strip() or "default"
    if tid == "default" and _alert_store is not None:
        return _alert_store
    if tid == "default":
        db_path = get_default_alert_db_path()
    else:
        base = data_path("tenants", tid)
        db_path = str(base / "alerts.db")
    if db_path not in _store_cache:
        _store_cache[db_path] = AlertStore(db_path=db_path)
    store = _store_cache[db_path]
    if tid == "default" and _alert_store is None:
        _alert_store = store
    return store


def _get_cogs_store(tenant_id: str = "default") -> CogsStore:
    tid = (tenant_id or "default").strip() or "default"
    if tid == "default":
        db_path = get_default_cogs_db_path()
    else:
        base = data_path("tenants", tid)
        db_path = str(base / "cogs.db")
    if db_path not in _cogs_store_cache:
        _cogs_store_cache[db_path] = CogsStore(db_path=db_path)
    return _cogs_store_cache[db_path]

_server_start_time: float = time.monotonic()

@asynccontextmanager
async def _lifespan(app):
    global _alert_engine, _daily_briefing_scheduler
    cfg = AmazonConfig.from_env()
    mode = "dry_run" if cfg.dry_run else "live"
    logger.info("Amazon MCP starting — mode=%s marketplace=%s seller=%s",
                mode, cfg.marketplace_id, cfg.seller_id or "(unset)")

    # ── Credential diagnostics ────────────────────────────────────────────────
    missing = cfg.validate_live()
    if missing:
        logger.warning("Live mode credential issues: %s", missing)
    if cfg.dry_run and cfg.sp_configured and not cfg.has_placeholder_credentials:
        logger.warning(
            "AMAZON_MCP_DRY_RUN=1 but real SP-API credentials detected — "
            "set AMAZON_MCP_DRY_RUN=0 to enable live SP-API calls"
        )
    if not cfg.dry_run and cfg.has_placeholder_credentials:
        logger.error(
            "LIVE mode with placeholder credentials — SP-API calls will fail with 401. "
            "Update credentials or set AMAZON_MCP_DRY_RUN=1"
        )

    if has_pro():
        from amazon_mcp_pro.server_ext import ensure_default_tenant

        ensure_default_tenant()

    if has_pro():
        from amazon_mcp_pro.server_ext import start_lifespan

        _alert_engine, _daily_briefing_scheduler = await start_lifespan(
            cfg=cfg,
            get_store=_get_store,
            ctx_for_tenant_fn=_ctx_for_tenant,
            fire_daily_briefing=_fire_scheduled_daily_briefing,
        )
    try:
        yield
    finally:
        logger.info("Amazon MCP shutting down")
        if has_pro():
            from amazon_mcp_pro.server_ext import stop_lifespan

            await stop_lifespan(_alert_engine, _daily_briefing_scheduler)
            _alert_engine = None
            _daily_briefing_scheduler = None
        logger.info("Amazon MCP shutdown complete")

_mcp_host = os.environ.get("FASTMCP_HOST", os.environ.get("AMAZON_MCP_HOST", "127.0.0.1"))
_mcp_port = int(os.environ.get("FASTMCP_PORT", os.environ.get("AMAZON_MCP_PORT", "8780")))
mcp = FastMCP("amazon-sp", lifespan=_lifespan, host=_mcp_host, port=_mcp_port)
install_mcp_api_key_middleware(mcp)
install_ip_allowlist_middleware(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health_endpoint(request: Request) -> Response:
    """Unauthenticated liveness probe for systemd / cockpit / SSH checks."""
    dry_run = os.environ.get("AMAZON_MCP_DRY_RUN", "1").strip() in ("1", "true", "yes")
    payload = {
        "ok": True,
        "service": "amazon-mcp",
        "version": __import__("amazon_mcp").__version__,
        "edition": "pro" if has_pro() else "core",
        "dry_run": dry_run,
    }
    return Response(content=json.dumps(payload), media_type="application/json")


@mcp.resource("amazon://alerts/pending")
async def pending_alerts_resource() -> str:
    """Live alert feed — subscribe for proactive push notifications."""
    alerts = _get_store().get_pending_alerts()
    return _json({
        "ok": True,
        "pending_count": len(alerts),
        "alerts": alerts[:20],
    })



_CTX_TTL_S = 60.0
_tenant_ctx_cache: dict[str, Any] = {"fp": "", "expires": 0.0, "values": {}}
_last_ctx_hit = False

_ENV_FP_KEYS = (
    "AMAZON_MCP_DRY_RUN",
    "AMAZON_LWA_CLIENT_ID",
    "AMAZON_LWA_CLIENT_SECRET",
    "AMAZON_LWA_REFRESH_TOKEN",
    "AMAZON_SP_API_REGION",
    "AMAZON_MARKETPLACE_ID",
    "AMAZON_SELLER_ID",
    "AMAZON_ADS_CLIENT_ID",
    "AMAZON_ADS_CLIENT_SECRET",
    "AMAZON_ADS_REFRESH_TOKEN",
    "AMAZON_ADS_PROFILE_ID",
    "AMAZON_CACHE_TTL",
)


def _env_fingerprint() -> str:
    blob = "|".join(os.environ.get(k, "") for k in _ENV_FP_KEYS)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]



def _reset_ctx_cache() -> None:
    global _last_ctx_hit
    _tenant_ctx_cache.update({"fp": "", "expires": 0.0, "values": {}})
    _last_ctx_hit = False


def _core_build_ctx(tenant_id: str = "default") -> tuple[AmazonConfig, SPAPIClient, AdsAPIClient]:
    """Single-tenant ctx from env (core edition)."""
    cfg = AmazonConfig.from_env()
    auth = LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token)
    limits = RateLimitRegistry()
    sp = SPAPIClient(cfg, auth, limits)
    ads_auth = LWAAuth(
        cfg.ads_client_id or cfg.lwa_client_id,
        cfg.ads_client_secret or cfg.lwa_client_secret,
        cfg.ads_refresh_token or cfg.lwa_refresh_token,
    )
    ads = AdsAPIClient(cfg, ads_auth, limits)
    return cfg, sp, ads


def _ctx_for_tenant(tenant_id: str = "default") -> tuple[AmazonConfig, SPAPIClient, AdsAPIClient]:
    global _last_ctx_hit
    tid = (tenant_id or "default").strip() or "default"
    if not has_pro():
        return _core_build_ctx(tid)
    from amazon_mcp_pro.server_ext import ctx_for_tenant as pro_ctx

    _ensure_default_tenant()
    return pro_ctx(
        tid,
        cache=_tenant_ctx_cache,
        env_fingerprint=_env_fingerprint,
        ttl_s=_CTX_TTL_S,
        last_hit=_last_ctx_hit_box,
    )


def _ctx() -> tuple[AmazonConfig, SPAPIClient, AdsAPIClient]:
    return _ctx_for_tenant("default")


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


async def _sp(coro: Any, *, tool: str = "") -> str:
    """Await an SP-API / Ads-API coroutine; returns structured JSON error on failure."""
    try:
        result = await coro
        return _json(result)
    except Exception as exc:
        label = f" in {tool}" if tool else ""
        logger.error("SP-API error%s: %s", label, exc, exc_info=True)
        return _json({"ok": False, "error": str(exc), "error_type": type(exc).__name__})





def _require_positive_price(price: float, field: str = "price") -> str | None:
    if price <= 0:
        return _json({"ok": False, "error": f"{field} must be greater than 0 (got {price})"})
    if price > 100_000:
        return _json({"ok": False, "error": f"{field} value {price} is implausibly large"})
    return None


def _require_valid_asin(asin: str) -> str | None:
    if not asin or len(asin) < 3:
        return _json({"ok": False, "error": "asin must be a non-empty string"})
    return None




def _registered_tool_names() -> list[str]:
    """Return sorted MCP tool names from the live FastMCP registry."""
    return sorted(t.name for t in mcp._tool_manager.list_tools())


def _ensure_default_tenant() -> None:
    if not has_pro():
        return
    from amazon_mcp_pro.server_ext import ensure_default_tenant

    ensure_default_tenant()


def _wire_tool_registry() -> None:
    scoring = "core"
    if has_pro():
        from amazon_mcp_pro.server_ext import scoring_version

        scoring = scoring_version()

    async def _sp_call(coro, tool: str = "") -> str:
        return await _sp(coro, tool=tool)

    init_tool_registry(
        ctx=_ctx_for_tenant,
        sp_call=_sp_call,
        json_dumps=_json,
        last_ctx_hit=lambda: _last_ctx_hit_box["value"],
        registered_tool_names=lambda: _registered_tool_names(),
        server_start_time=_server_start_time,
        alert_engine_getter=lambda: _alert_engine,
        get_store=_get_store,
        get_cogs_store=_get_cogs_store,
        ensure_default_tenant=_ensure_default_tenant,
        version=__import__("amazon_mcp").__version__,
        scoring_version=scoring,
    )
    register_domain_tools(mcp)


_wire_tool_registry()


# domain tool re-exports (TOOL_HANDLERS + backward-compat imports)
for _name, _fn in _DOMAIN_TOOL_EXPORTS.items():
    globals()[_name] = _fn




# Domain tools via register_domain_tools()

# ═══════════════════════════════════════════════════════════════════════════════
# AUTH HEALTH (intel P0 — proactive refresh diagnostics)
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# DAG EXECUTION — [PLAN] -> [EXEC] -> [AUDIT] + FastForward resume
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def run_dag_plan(operation: str, params_json: str = "{}") -> str:
    """
    Execute an SP-API operation via DAG phases: [PLAN] validate -> [EXEC] call -> [AUDIT] refiner.
    Checkpoints each phase; resume with resume_dag_plan after interruption.
    operation: SP-API method name (e.g. get_catalog_item / get_inventory_summaries)
    params_json: JSON params for the operation (e.g. '{"asin": "B0001"}')
    """
    import uuid as _uuid
    try:
        params = json.loads(params_json) if params_json.strip() not in ("{}", "") else {}
    except json.JSONDecodeError as e:
        return _json({"ok": False, "error": f"params_json invalid JSON: {e}"})
    tenant_id = os.environ.get("AMAZON_TENANT_ID", "default")
    cfg, sp, _ = _ctx_for_tenant(tenant_id)
    plan_id = f"dag-{operation}-{_uuid.uuid4().hex[:8]}"
    executor = DagExecutor(sp_client=sp, dry_run=cfg.dry_run)
    state = await executor.execute(plan_id, operation, params)
    return _json({
        "ok": state.status == "complete",
        "plan_id": plan_id,
        "status": state.status,
        "phases": {k: v.get("status") for k, v in state.phases.items()},
        "audit_summary": state.phases.get("AUDIT", {}).get("result", {}),
    })


@mcp.tool()
async def resume_dag_plan(plan_id: str) -> str:
    """
    Resume an interrupted DAG plan from a FastForward checkpoint.
    plan_id: returned by run_dag_plan
    """
    tenant_id = os.environ.get("AMAZON_TENANT_ID", "default")
    cfg, sp, _ = _ctx_for_tenant(tenant_id)
    executor = DagExecutor(sp_client=sp, dry_run=cfg.dry_run)
    checkpoint = FastForward.load_checkpoint(plan_id)
    if not checkpoint:
        if cfg.dry_run:
            return _json({"ok": True, "plan_id": plan_id, "status": "no_checkpoint", "message": "dry_run: no checkpoint to resume, nothing to do"})
        return _json({"ok": False, "error": f"No checkpoint found for plan_id='{plan_id}'"})
    completed_before = FastForward.get_completed_phases(plan_id)
    state = await executor.resume(plan_id)
    return _json({
        "ok": state.status == "complete",
        "plan_id": plan_id,
        "resumed_from": sorted(completed_before),
        "status": state.status,
        "phases": {k: v.get("status") for k, v in state.phases.items()},
    })


async def _get_sp_and_dry_run():
    cfg, sp, _ = _ctx()
    return sp, cfg.dry_run


async def _get_ads_and_dry_run():
    cfg, _, ads = _ctx()
    return ads, cfg.dry_run


def _wire_pro_extensions() -> None:
    from amazon_mcp_pro.server_ext import register_scenario_tools

    exports = register_scenario_tools(
        mcp,
        ctx_for_tenant_fn=_ctx_for_tenant,
        get_store=_get_store,
        get_cogs_store=_get_cogs_store,
        json_dumps=_json,
    )
    globals().update(exports)
    if has_pro():
        from amazon_mcp_pro.server_ext import attach_slack_services, build_slack_handler, register_routes

        global _slack_interaction_handler
        _slack_interaction_handler = build_slack_handler(_get_store)
        register_routes(
            mcp,
            get_store=_get_store,
            ctx_for_tenant_fn=_ctx_for_tenant,
            json_dumps=_json,
            slack_handler=_slack_interaction_handler,
        )
        attach_slack_services(
            _slack_interaction_handler,
            get_sp_and_dry_run=_get_sp_and_dry_run,
            get_ads_and_dry_run=_get_ads_and_dry_run,
        )


_wire_pro_extensions()


TOOL_HANDLERS: dict[str, Any] = {
    # System
    "amazon_health": lambda: amazon_health(),
    "amazon_system": lambda: amazon_system("health"),
    # Account
    "amazon_account": lambda: amazon_account("feedback"),
    # Catalog
    "amazon_catalog": lambda: amazon_catalog("lookup", asin="B0POC00001"),
    "amazon_catalog_search": lambda: amazon_catalog("search", keywords="python mcp server"),
    "amazon_catalog_competitor": lambda: amazon_catalog("competitor_insights", asin="B0POC00001", category="electronics"),
    # Pricing
    "amazon_pricing": lambda: amazon_pricing("product_pricing", asins="B0POC00001"),
    "amazon_pricing_profit": lambda: amazon_pricing("profit_analysis", asin="B0POC00001", sale_price=29.99, cogs=8.50),
    # Orders
    "amazon_orders": lambda: amazon_orders("revenue_summary"),
    "amazon_orders_list": lambda: amazon_orders("list"),
    # Inventory
    "amazon_inventory": lambda: amazon_inventory("list_asins"),
    "amazon_inventory_health": lambda: amazon_inventory("health"),
    "amazon_inventory_aging": lambda: amazon_inventory("aging_inventory"),
    "amazon_inventory_fnsku_reorder": lambda: amazon_inventory("fnsku_reorder"),
    # Report
    "amazon_report": lambda: amazon_report("create", report_type="sales_traffic"),
    "amazon_report_brand": lambda: amazon_report("brand_analytics", report_type="search_performance"),
    # Ads
    "amazon_ads": lambda: amazon_ads("profile"),
    "amazon_ads_campaigns": lambda: amazon_ads("campaign_list"),
    # Finance
    "amazon_finance": lambda: amazon_finance("financial_summary"),
    # Fulfillment
    "amazon_fulfillment": lambda: amazon_fulfillment("get_inbound_plan", inbound_plan_id="FBA-PLAN-DRY-001"),
    "amazon_fulfillment_reimbursement": lambda: amazon_fulfillment("reimbursement_summary"),
    # Analytics
    "amazon_analytics": lambda: amazon_analytics("sales_traffic"),
    # Alerts
    "amazon_alerts": lambda: amazon_alerts("alert_config"),
    "amazon_alerts_pending": lambda: amazon_alerts("pending_alerts"),
    # Insights
    "amazon_insights": lambda: amazon_insights("operations_health", asins="B0POC00001"),
    "amazon_insights_margin": lambda: amazon_insights("protect_margin", asin="B0POC00001"),
    # Notify
    "amazon_notify": lambda: amazon_notify("notification_config"),
    # Billing
    "amazon_billing": lambda: amazon_billing("usage_summary"),
    # Daily shortcut
    "amazon_daily": lambda: amazon_daily(),
    # Scenarios & DAG
    "run_scenario": lambda: run_scenario("profit_protection", asins="B0POC00001"),
    "run_dag_plan": lambda: run_dag_plan("get_catalog_item", "{}"),
    "resume_dag_plan": lambda: resume_dag_plan("dag-dry-001"),
}


async def _fire_scheduled_daily_briefing() -> None:
    """Background job: daily briefing + Slack push when schedule is enabled (pro)."""
    if not has_pro():
        return

    async def _insights(asin: str) -> dict:
        try:
            raw = await category_competitor_insights(asin)
            return json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception as exc:
            logger.warning("category_competitor_insights failed for %s: %s", asin, exc)
            return {"ok": False, "asin": asin, "error": str(exc)}

    from amazon_mcp_pro.server_ext import fire_scheduled_daily_briefing

    await fire_scheduled_daily_briefing(
        ctx_fn=_ctx,
        get_store=_get_store,
        get_cogs_store=_get_cogs_store,
        category_insights_fn=_insights,
    )


# ── Backward-compat shims (importable by tests; NOT registered as MCP tools) ──
# These call the domain handlers directly and return the flat (unwrapped) JSON
# so that existing test assertions continue to work unchanged.

from amazon_mcp.tools.registry import invoke as _invoke_domain


async def _flat(domain: str, action: str, params: dict) -> str:
    tid = os.environ.get("AMAZON_TENANT_ID", "default")
    params.setdefault("tenant_id", tid)
    return _json(await _invoke_domain(domain, action, params))


async def configure_inventory_alert(sku: str, asin: str, min_qty: int) -> str:
    return await _flat("alerts", "configure_inventory", {"sku": sku, "asin": asin, "min_qty": min_qty})

async def add_price_watch(asin: str, baseline_price: float, alert_pct: float = 0.05, direction: str = "any") -> str:
    return await _flat("alerts", "add_price_watch", {"asin": asin, "baseline_price": baseline_price, "alert_pct": alert_pct, "direction": direction})

async def get_pending_alerts(limit: int = 20) -> str:
    return await _flat("alerts", "pending_alerts", {"limit": limit})

async def dismiss_alert(alert_id: str) -> str:
    return await _flat("alerts", "dismiss", {"alert_id": alert_id})

async def get_alert_config() -> str:
    return await _flat("alerts", "alert_config", {})

async def trigger_manual_check() -> str:
    return await _flat("alerts", "manual_check", {})

async def how_long_inventory_last(sku: str, daily_sales_rate: float = 0.0) -> str:
    return await _flat("insights", "inventory_last", {"sku": sku, "daily_sales_rate": daily_sales_rate})

async def protect_profit_margin(asin: str, target_margin: float = 0.3) -> str:
    return await _flat("insights", "protect_margin", {"asin": asin, "target_margin": target_margin})

async def competitor_price_alert(asin: str, threshold_pct: float = 0.05) -> str:
    return await _flat("insights", "competitor_price_alert", {"asin": asin, "threshold_pct": threshold_pct})

async def get_operations_health_report(asins: str) -> str:
    return await _flat("insights", "operations_health", {"asins": asins})

async def get_fee_estimate(asin: str, price: float) -> str:
    return await _flat("pricing", "fee_estimate", {"asin": asin, "price": price})

async def get_profit_analysis(asin: str, sale_price: float, cogs: float = 0.0, days: int = 30) -> str:
    return await _flat("pricing", "profit_analysis", {"asin": asin, "sale_price": sale_price, "cogs": cogs, "days": days})

async def category_competitor_insights(asin: str, category: str = "") -> str:
    return await _flat("catalog", "competitor_insights", {"asin": asin, "category": category})

async def get_notification_config() -> str:
    return await _flat("notify", "notification_config", {})

async def test_notification_channel(channel: str) -> str:
    return await _flat("notify", "test_channel", {"channel": channel})


def main() -> None:
    log_level = os.environ.get("AMAZON_MCP_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    transport = os.environ.get("AMAZON_MCP_TRANSPORT", "stdio").strip().lower()
    if transport in ("streamable-http", "streamable_http"):
        os.environ.setdefault("FASTMCP_HOST", os.environ.get("AMAZON_MCP_HOST", "127.0.0.1"))
        os.environ.setdefault("FASTMCP_PORT", os.environ.get("AMAZON_MCP_PORT", "8780"))
        mcp.run(transport="streamable-http")
    elif transport == "sse":
        os.environ.setdefault("FASTMCP_HOST", os.environ.get("AMAZON_MCP_HOST", "127.0.0.1"))
        os.environ.setdefault("FASTMCP_PORT", os.environ.get("AMAZON_MCP_PORT", "8780"))
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
