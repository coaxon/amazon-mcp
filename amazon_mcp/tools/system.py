"""amazon_system domain handlers."""
from __future__ import annotations

import time
from typing import Any

from amazon_mcp.tools.deps import ctx_from_params, get_tool_deps, tenant_id_from_params

HandlerFn = Any  # kept loose for registry typing


async def health(_params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    t0 = time.perf_counter()
    cfg, _, _ = ctx_from_params(_params)
    ctx_build_ms = round((time.perf_counter() - t0) * 1000, 2)
    tool_names = deps.registered_tool_names()
    return {
        "ok": True,
        "service": "amazon-mcp",
        "version": deps.version,
        "scoring_version": deps.scoring_version,
        "ctx_build_ms": ctx_build_ms,
        "ctx_cached": deps.last_ctx_hit(),
        "dry_run": cfg.dry_run,
        "sp_api_configured": cfg.sp_configured,
        "ads_api_configured": cfg.ads_configured,
        "marketplace_id": cfg.marketplace_id,
        "seller_id": cfg.seller_id or "not_set",
        "region": cfg.sp_region,
        "cache_ttl_seconds": cfg.cache_ttl_seconds,
        "tool_count": len(tool_names),
        "available_tools": tool_names,
    }


async def auth_token(_params: dict[str, Any]) -> dict[str, Any]:
    cfg, sp, ads = ctx_from_params(_params)
    sp_ttl = round(sp.auth.token_ttl_seconds, 0)
    ads_ttl = round(ads.auth.token_ttl_seconds, 0)
    return {
        "ok": True,
        "sp_api_token": {
            "ttl_seconds": sp_ttl,
            "needs_refresh_soon": sp_ttl < 300,
            "has_token": bool(sp.auth._access_token),
        },
        "ads_api_token": {
            "ttl_seconds": ads_ttl,
            "needs_refresh_soon": ads_ttl < 300,
            "has_token": bool(ads.auth._access_token),
        },
        "shared_file_cache": sp.auth._shared_cache,
        "dry_run": cfg.dry_run,
    }


async def metrics(_params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    cfg, sp, _ = ctx_from_params(_params)
    uptime_s = round(time.monotonic() - deps.server_start_time)
    rate_stats = sp.limits.stats
    engine = deps.alert_engine_getter() if deps.alert_engine_getter else None
    engine_stats: dict[str, Any] = {}
    if engine:
        engine_stats = {
            "running": engine._running,
            "poll_count": engine.poll_count,
            "emit_count": engine.emit_count,
            "suppress_count": engine.suppress_count,
        }
    pending = deps.get_store().count_pending() if deps.get_store else 0
    return {
        "ok": True,
        "uptime_s": uptime_s,
        "mode": "dry_run" if cfg.dry_run else "live",
        "marketplace_id": cfg.marketplace_id,
        "ctx_cache_hit": deps.last_ctx_hit(),
        "rate_limit": {
            "requests": rate_stats.requests,
            "throttled": rate_stats.throttled,
            "backoff_sleeps": rate_stats.backoff_sleeps,
            "total_backoff_s": round(rate_stats.total_backoff_s, 3),
        },
        "alert_engine": engine_stats,
        "pending_alerts": pending,
        "response_cache_size": sp._cache.size,
    }


async def marketplaces(_params: dict[str, Any]) -> dict[str, Any]:
    deps = get_tool_deps()
    _, sp, _ = ctx_from_params(_params)
    raw = await deps.sp_call(sp.get_marketplace_participations(), "get_marketplace_participations")
    import json
    return json.loads(raw)


HANDLERS = {
    "health": health,
    "auth_token": auth_token,
    "metrics": metrics,
    "marketplaces": marketplaces,
}
