"""Domain MCP tools — amazon_{domain} consolidated tools, no legacy aliases."""
from __future__ import annotations

from typing import Any

from amazon_mcp.tools.registry import dispatch_domain

EXPORTS: dict[str, Any] = {}


def _p(**kwargs) -> dict:
    """Build params dict, dropping empty-string values but keeping zeros and False."""
    return {k: v for k, v in kwargs.items() if v is not None and v != ""}


def register_domain_tools(mcp: Any) -> None:

    # ── system ──────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_health() -> str:
        """Check MCP server status, credential configuration, and marketplace info."""
        return await dispatch_domain("system", "health", {})

    @mcp.tool()
    async def amazon_system(action: str) -> str:
        """System domain.
        action: health | auth_token | metrics | marketplaces
        """
        return await dispatch_domain("system", action, {})

    # ── account ─────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_account(
        action: str,
        days: int = 90,
        notification_type: str = "",
        subscription_id: str = "",
        webhook_url: str = "",
    ) -> str:
        """Account domain — seller feedback and SP-API push notification management.
        action:
          feedback                      — seller feedback summary (last {days} days)
          list_subscriptions            — list active subscriptions for notification_type
          subscription_status           — check all common notification types at once
          subscribe_offer_changed       — subscribe to ANY_OFFER_CHANGED (price drops)
          subscribe_inventory_availability — subscribe to FBA_INVENTORY_AVAILABILITY_CHANGES
          subscribe_listings_status     — subscribe to LISTINGS_ITEM_STATUS_CHANGE (active/suppressed)
          subscribe_listings_issues     — subscribe to LISTINGS_ITEM_ISSUES_CHANGE (compliance errors)
          subscribe_pricing_health      — subscribe to PRICING_HEALTH (Buy Box eligibility)
          unsubscribe                   — delete subscription by notification_type + subscription_id
        days: lookback for feedback (default 90)
        notification_type: required for list_subscriptions / unsubscribe
        subscription_id: required for unsubscribe
        webhook_url: override destination URL (subscribe actions; defaults to AMAZON_MCP_NOTIFICATION_WEBHOOK_URL env)
        """
        return await dispatch_domain("account", action, _p(days=days, notification_type=notification_type, subscription_id=subscription_id, webhook_url=webhook_url))

    # ── catalog ─────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_catalog(
        action: str,
        asin: str = "",
        asins: str = "",
        keywords: str = "",
        category: str = "",
        page_size: int = 20,
    ) -> str:
        """Catalog domain.
        action: lookup | bulk_lookup | search | listing_quality | competitor_insights
        asin: single ASIN (lookup / listing_quality / competitor_insights)
        asins: comma-separated ASINs (bulk_lookup, max 20)
        keywords: search terms (search)
        category: optional category filter (search / competitor_insights)
        page_size: search results per page (default 20)
        """
        return await dispatch_domain("catalog", action, _p(asin=asin, asins=asins, keywords=keywords, category=category, page_size=page_size))

    # ── pricing ─────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_pricing(
        action: str,
        asin: str = "",
        asins: str = "",
        price: float = 0.0,
        sale_price: float = 0.0,
        cogs: float = 0.0,
        days: int = 30,
    ) -> str:
        """Pricing domain.
        action: product_pricing | competitive_offers | fee_estimate | profit_analysis
        asins: comma-separated (product_pricing)
        asin: single ASIN (competitive_offers / fee_estimate / profit_analysis)
        price: listing price for fee_estimate
        sale_price: selling price for profit_analysis
        cogs: cost of goods for profit_analysis
        days: lookback for profit_analysis
        """
        return await dispatch_domain("pricing", action, _p(asin=asin, asins=asins, price=price, sale_price=sale_price, cogs=cogs, days=days))

    # ── orders ──────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_orders(
        action: str,
        days: int = 7,
        status: str = "",
        order_id: str = "",
        next_token: str = "",
    ) -> str:
        """Orders domain.
        action: revenue_summary | list | order_details | sales_by_asin | next_page
        days: lookback window (revenue_summary / list / sales_by_asin)
        status: filter by order status (list)
        order_id: specific order (order_details)
        next_token: pagination cursor from previous list call (next_page)
        """
        return await dispatch_domain("orders", action, _p(days=days, status=status, order_id=order_id, next_token=next_token))

    # ── inventory ───────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_inventory(
        action: str,
        skus: str = "",
        sku: str = "",
        daily_sales_rate: float = 0.0,
        lead_time_days: int = 14,
        safety_stock_days: int = 14,
        warn_days: int = 150,
    ) -> str:
        """Inventory domain.
        action: levels | list_asins | health | stranded | suppressed | reorder_calculator | aging_inventory | fnsku_reorder | restock_recommendations | ipi_score
        skus: comma-separated SKUs to filter (levels)
        sku: single SKU (reorder_calculator)
        daily_sales_rate: units/day override for reorder calc
        lead_time_days: supplier lead time in days (reorder_calculator / fnsku_reorder, default 14)
        safety_stock_days: safety buffer in days (reorder_calculator / fnsku_reorder, default 14)
        warn_days: days-in-FBA threshold to trigger LTSF warning (aging_inventory, default 150; Amazon LTSF = 181d)
        restock_recommendations — Amazon official GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT; returns actionable items sorted by urgency (days-of-supply asc)
        ipi_score — IPI from GET_FBA_INVENTORY_PLANNING_DATA; score <400 triggers Amazon storage restrictions
        """
        return await dispatch_domain("inventory", action, _p(skus=skus, sku=sku, daily_sales_rate=daily_sales_rate, lead_time_days=lead_time_days, safety_stock_days=safety_stock_days, warn_days=warn_days))

    # ── report ──────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_report(
        action: str,
        report_type: str = "",
        days: int = 7,
        period: str = "WEEK",
        report_id: str = "",
        source: str = "sp",
        document_id: str = "",
    ) -> str:
        """Report domain.
        action: create | status | download | brand_analytics
        report_type for create:
          sales_traffic | inventory | orders | settlement | returns | fees | listings | reimbursements
        report_type for brand_analytics (requires Brand Registry access):
          search_performance  — search terms + click/conversion share
          market_basket       — frequently bought together
          repeat_purchase     — repeat buyer rate by ASIN
          demographics        — buyer demographics (age, income, education)
          item_comparison     — which competing ASINs customers viewed alongside yours
          alternate_purchase  — which ASINs customers bought instead of yours
        days: lookback window for create / brand_analytics
        period: WEEK | MONTH for brand_analytics (default WEEK)
        report_id: from create response (status)
        source: sp | ads (status, default sp)
        document_id: from status response (download)
        """
        return await dispatch_domain("report", action, _p(report_type=report_type, days=days, period=period, report_id=report_id, source=source, document_id=document_id))

    # ── ads ─────────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_ads(
        action: str,
        state: str = "enabled",
        campaign_id: str = "",
        days: int = 7,
    ) -> str:
        """Advertising domain.
        action: profile | campaign_list | keyword_performance | sponsored_metrics | search_term_performance | campaign_performance | product_ad_performance | pause_campaign
        state: campaign state filter for campaign_list (enabled / paused / archived)
        campaign_id: filter by campaign (keyword_performance)
        days: lookback window for performance actions
        """
        return await dispatch_domain("ads", action, _p(state=state, campaign_id=campaign_id, days=days))

    # ── finance ─────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_finance(
        action: str,
        days: int = 30,
        csv_content: str = "",
        asin: str = "",
    ) -> str:
        """Finance domain.
        action:
          financial_summary  — aggregated P&L summary (Finances v0)
          transaction_list   — itemized transactions with fee breakdowns (Finances v2024)
          fee_breakdown      — aggregate fees by type across all transactions (Finances v2024)
          import_cogs        — import cost-of-goods CSV (columns: asin,cogs)
          get_cogs           — retrieve stored COGS by ASIN
        days: lookback for financial_summary / transaction_list / fee_breakdown
        csv_content: CSV with asin,cogs columns (import_cogs)
        asin: filter by ASIN (get_cogs; omit for all)
        """
        return await dispatch_domain("finance", action, _p(days=days, csv_content=csv_content, asin=asin))

    # ── fulfillment ──────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_fulfillment(
        action: str,
        inbound_plan_id: str = "",
        operation_id: str = "",
        items_json: str = "",
        source_address_json: str = "",
        plan_name: str = "",
        days: int = 30,
    ) -> str:
        """FBA fulfillment domain.
        action: create_inbound_plan | get_inbound_plan | operation_status | reimbursement_summary
        items_json: JSON array of {msku, quantity} (create_inbound_plan)
        source_address_json: JSON address object (create_inbound_plan)
        plan_name: optional label (create_inbound_plan)
        inbound_plan_id: from create response (get_inbound_plan)
        operation_id: from create response (operation_status)
        days: lookback for reimbursement_summary
        """
        return await dispatch_domain("fulfillment", action, _p(inbound_plan_id=inbound_plan_id, operation_id=operation_id, items_json=items_json, source_address_json=source_address_json, plan_name=plan_name, days=days))

    # ── analytics ───────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_analytics(
        action: str,
        days: int = 30,
        granularity: str = "DAY",
        query_id: str = "",
        graphql_query: str = "",
    ) -> str:
        """Data Kiosk / analytics domain.
        action: sales_traffic | kiosk_status | custom_kiosk_query
        days: lookback window (sales_traffic)
        granularity: DAY | WEEK | MONTH (sales_traffic)
        query_id: from sales_traffic response (kiosk_status)
        graphql_query: raw GraphQL string (custom_kiosk_query)
        """
        return await dispatch_domain("analytics", action, _p(days=days, granularity=granularity, query_id=query_id, graphql_query=graphql_query))

    # ── alerts ───────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_alerts(
        action: str,
        sku: str = "",
        asin: str = "",
        min_qty: int = 0,
        baseline_price: float = 0.0,
        alert_pct: float = 0.05,
        direction: str = "any",
        alert_id: str = "",
        limit: int = 20,
    ) -> str:
        """Proactive monitoring & alerts domain.
        action: configure_inventory | add_price_watch | pending_alerts | dismiss | alert_config | manual_check
        sku / asin / min_qty: for configure_inventory
        asin / baseline_price / alert_pct / direction: for add_price_watch
        alert_id: for dismiss
        limit: max alerts to return (pending_alerts, default 20)
        """
        params = _p(sku=sku, asin=asin, baseline_price=baseline_price, alert_pct=alert_pct, direction=direction, alert_id=alert_id, limit=limit)
        if min_qty:
            params["min_qty"] = min_qty
        return await dispatch_domain("alerts", action, params)

    # ── insights ─────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_insights(
        action: str,
        asins: str = "",
        asin: str = "",
        sku: str = "",
        daily_sales_rate: float = 0.0,
        target_margin: float = 0.3,
        threshold_pct: float = 0.05,
    ) -> str:
        """Business intelligence / decision-layer domain.
        action: operations_health | inventory_last | protect_margin | competitor_price_alert
        asins: comma-separated ASINs (operations_health)
        asin: single ASIN (protect_margin / competitor_price_alert)
        sku: single SKU (inventory_last)
        daily_sales_rate: units/day override for inventory_last
        target_margin: minimum acceptable margin 0-1 (protect_margin, default 0.3)
        threshold_pct: price gap threshold 0-1 (competitor_price_alert, default 0.05)
        """
        return await dispatch_domain("insights", action, _p(asins=asins, asin=asin, sku=sku, daily_sales_rate=daily_sales_rate, target_margin=target_margin, threshold_pct=threshold_pct))

    # ── notify ───────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_notify(
        action: str,
        channel: str = "",
    ) -> str:
        """Notification channel domain.
        action: notification_config | set_briefing_prefs | test_channel
        channel: slack | email | discord | webhook (test_channel)
        """
        return await dispatch_domain("notify", action, _p(channel=channel))

    # ── listings CRUD ─────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_listings(
        action: str,
        sku: str = "",
        price: float = 0.0,
        currency: str = "USD",
        quantity: int = -1,
        confirm: bool = False,
    ) -> str:
        """Listings Items CRUD — read and update individual listing attributes.

        action:
          get_listing      — read current price, status, ASIN, offers for a SKU
          update_price     — change listing price (preview by default; confirm=True to apply)
          update_quantity  — change FBM fulfillable quantity (confirm=True to apply)
          deactivate_listing — set status INACTIVE, hiding from search (confirm=True to apply)
          activate_listing   — restore listing to ACTIVE/BUYABLE (confirm=True to apply)
          delete_listing     — permanently delete SKU + ASIN association (confirm=True to apply)

        Write operations require confirm=True to execute. Without it they return a
        preview of the proposed change — the same UX as FBA inbound plan preview/confirm.

        sku: seller SKU (required for all actions)
        price: new listing price in USD (update_price)
        currency: price currency, default USD (update_price)
        quantity: new FBM quantity (update_quantity; must be ≥ 0)
        confirm: set True to execute write; default False (preview only)
        """
        p = _p(sku=sku, currency=currency)
        if price > 0:
            p["price"] = price
        if quantity >= 0:
            p["quantity"] = quantity
        if confirm:
            p["confirm"] = True
        return await dispatch_domain("listings", action, p)

    # ── billing ──────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_billing(
        action: str,
        days: int = 30,
        tool_name: str = "",
        monthly_limit: int = -1,
    ) -> str:
        """Usage metering + quota enforcement domain.

        action:
          usage_summary  — call volume by tool for last {days} days + monthly quota status
          check_quota    — check if current tenant is within monthly call limit
          month_usage    — current-month call count vs limit
          set_quota      — set custom monthly call limit for a tenant (admin)
          tier_limits    — show default monthly limits per service tier

        days: lookback for usage_summary (default 30)
        tool_name: filter by specific tool (check_quota)
        monthly_limit: for set_quota (integer, 0 = unlimited)

        Default tier limits:
          starter: 5,000 calls/month · standard: 20,000 · advanced: 50,000 · global_suite: unlimited
        """
        p = _p(days=days, tool_name=tool_name)
        if monthly_limit >= 0:
            p["monthly_limit"] = monthly_limit
        return await dispatch_domain("billing", action, p)

    # ── Mercado Libre ─────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_meli(
        action: str,
        days: int = 7,
        site_ids: str = "",
        cover_days_threshold: int = 5,
        fx_threshold_pct: float = 0.08,
    ) -> str:
        """Mercado Libre (美客多) domain — LATAM orders, inventory, and daily briefing.

        action:
          orders_list       — orders across configured ML sites for last {days} days
          inventory_get     — FULL / self-ship inventory across configured sites
          account_health    — ML account reputation and thermometer score
          daily_snapshot    — composite: orders + inventory + LATAM rules alerts
          configure_site    — show/update configured site IDs

        site_ids: comma-separated ML site codes (MLA=Argentina, MLB=Brasil, MLM=México,
                  MCO=Colombia, MLC=Chile, MLU=Uruguay, MPE=Perú)
        days: lookback window for orders (default 7)
        cover_days_threshold: low-stock alert threshold in days for FULL mode (default 5)
        fx_threshold_pct: FX drift threshold for price advisory (default 0.08 = 8%)

        Requires: MELI_APP_ID, MELI_CLIENT_SECRET, MELI_REFRESH_TOKEN env vars (live mode).
        Dry-run fixtures enabled when AMAZON_MCP_DRY_RUN=1.
        """
        return await dispatch_domain("meli", action, _p(
            days=days, site_ids=site_ids,
            cover_days_threshold=cover_days_threshold,
            fx_threshold_pct=fx_threshold_pct,
        ))

    # ── TikTok Shop ───────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_tiktok(
        action: str,
        days: int = 7,
    ) -> str:
        """TikTok Shop domain (Phase P1 — read-only).

        action:
          orders_list       — recent TikTok orders with SKU-level breakdown
          inventory_get     — FBT / self-ship product inventory
          daily_snapshot    — orders + inventory + velocity flags
          connection_status — check TikTok API credential configuration

        days: lookback window for orders (default 7)

        Requires: TIKTOK_APP_KEY, TIKTOK_APP_SECRET, TIKTOK_ACCESS_TOKEN, TIKTOK_SHOP_CIPHER.
        Write operations (price, ads) planned for P4 Command Center.
        """
        return await dispatch_domain("tiktok", action, _p(days=days))

    # ── Cross-platform ────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_cross_platform(
        action: str,
        days: int = 7,
        platforms: str = "amazon,meli,tiktok",
        days_since_price_change: int = 30,
        fx_threshold_pct: float = 0.08,
    ) -> str:
        """Cross-platform intelligence — unified view across Amazon + Mercado Libre + TikTok.

        action:
          inventory_sync    — compare inventory per SKU across all platforms; flags stockout risk
                              and channel priority buffer recommendations
          revenue_compare   — revenue breakdown and channel mix percentage
          latam_rules_check — LATAM-specific rules: FULL cover, FX drift advisory, velocity divergence
          connection_status — show all platform connection states and roadmap

        platforms: comma-separated (default "amazon,meli,tiktok")
        days: lookback for orders/revenue (default 7)
        days_since_price_change: for FX advisory rule in latam_rules_check
        fx_threshold_pct: FX drift alert threshold (default 0.08 = 8%)

        Rule catalog:
          cross_channel_stockout_risk   — one channel near OOS while others have stock
          channel_priority_buffer       — recommends allocation to highest-margin channel
          site_velocity_divergence      — ML site divergence (MLA hot / MLM cold)
          price_drift_vs_fx             — margin erosion from FX move vs static list price
        """
        return await dispatch_domain("cross_platform", action, _p(
            days=days, platforms=platforms,
            days_since_price_change=days_since_price_change,
            fx_threshold_pct=fx_threshold_pct,
        ))

    # ── RTO Geo Intelligence ──────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_rto_geo(
        action: str,
        days: int = 30,
        threshold_rate: float = 0.15,
        multiplier: float = 2.0,
        min_orders: int = 5,
        top_n: int = 3,
    ) -> str:
        """Return-To-Origin (退货) geographic intelligence by ship-state (Phase R1–R3).

        action:
          returns_geo_cluster    — full cluster: return rate per state, sorted by rate
          rto_region_alert       — top-N high-RTO state alerts with Slack-ready messages
          rto_ads_correlation    — (Phase R3 advisory) correlate high-RTO states with ad spend
          rto_health_score_factor — compute 0–100 regional RTO risk factor for ops health score

        days: lookback window for report pull (live mode, default 30)
        threshold_rate: absolute return rate to trigger alert (default 0.15 = 15%)
        multiplier: also alert if state rate ≥ N× global average (default 2.0)
        min_orders: minimum orders in state for alert to fire (default 5)
        top_n: number of high-RTO alerts to return (rto_region_alert, default 3)

        Privacy: only state-level aggregates stored, no order-level PII.
        Advisory: rto_ads_correlation is read-only — no auto-write to campaigns.
        """
        return await dispatch_domain("rto_geo", action, _p(
            days=days, threshold_rate=threshold_rate,
            multiplier=multiplier, min_orders=min_orders, top_n=top_n,
        ))

    # ── Command Center (P4) ───────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_command_center(
        action: str,
        platform: str = "meli",
        sku: str = "",
        quantity: int = -1,
        price: float = 0.0,
        currency: str = "USD",
        confirm: bool = False,
        confirm_id: str = "",
        reason: str = "",
        limit: int = 20,
    ) -> str:
        """Cross-platform write Command Center — preview → queue → confirm → execute (P4).

        All write operations require explicit confirm=True to queue, then a separate
        confirm_write call to execute. No auto-execution. Full audit trail.

        action:
          sync_inventory   — preview/queue inventory count update to a platform
          sync_price       — preview/queue listing price update to a platform
          confirm_write    — execute a queued write by confirm_id
          cancel_write     — cancel a pending write by confirm_id
          list_pending     — list all PENDING write intents
          audit_log        — return recent audit log entries
          connection_status — write executor readiness and roadmap

        platform: target platform (amazon | meli | tiktok)
        sku: seller SKU (sync_inventory / sync_price)
        quantity: new inventory quantity (sync_inventory, must be ≥ 0)
        price: new listing price (sync_price, must be > 0)
        currency: price currency (sync_price, default USD)
        confirm: set True to queue the write (default False = preview only)
        confirm_id: from previous sync_* response (confirm_write / cancel_write)
        reason: cancellation reason (cancel_write)
        limit: max entries returned (list_pending / audit_log, default 20)

        Guardrails: preview_required=True, confirm_gate=True, idempotency=True, audit_trail=True
        """
        p = _p(platform=platform, sku=sku, currency=currency, reason=reason, confirm_id=confirm_id)
        if quantity >= 0:
            p["quantity"] = quantity
        if price > 0:
            p["price"] = price
        if confirm:
            p["confirm"] = True
        if limit != 20:
            p["limit"] = limit
        return await dispatch_domain("command_center", action, p)

    # ── Cross-Tenant Benchmarks ───────────────────────────────────────────────
    @mcp.tool()
    async def amazon_benchmark(
        action: str,
        acos_pct: float = 0.0,
        net_margin_pct: float = 0.0,
        return_rate_pct: float = 0.0,
        inventory_health: float = 0.0,
        account_health: float = 0.0,
        reorder_fill_rate: float = 0.0,
        category: str = "general",
    ) -> str:
        """Cross-tenant industry benchmarks — anonymized percentile rankings.

        action:
          get_percentile        — percentile rank for one or more submitted metrics
          acos_benchmark        — quick single-metric ACOS percentile check
          margin_benchmark      — quick single-metric net margin percentile check
          category_comparison   — category-adjusted benchmark medians
          full_benchmark_report — all submitted metrics + ranked improvement opportunities

        Metrics (submit any combination):
          acos_pct            — advertising cost of sale percentage
          net_margin_pct      — net profit margin percentage
          return_rate_pct     — FBA return rate percentage
          inventory_health    — IPI-style score 0–100
          account_health      — Amazon account health score (0–200)
          reorder_fill_rate   — % of reorder points met on time

        category: adjust benchmarks for electronics | apparel | home | general (default)

        Privacy: only anonymized aggregate distributions stored.
        Minimum 5-tenant pool required before percentiles are valid.
        """
        p = _p(category=category)
        if acos_pct > 0:
            p["acos_pct"] = acos_pct
        if net_margin_pct != 0:
            p["net_margin_pct"] = net_margin_pct
        if return_rate_pct > 0:
            p["return_rate_pct"] = return_rate_pct
        if inventory_health > 0:
            p["inventory_health"] = inventory_health
        if account_health > 0:
            p["account_health"] = account_health
        if reorder_fill_rate > 0:
            p["reorder_fill_rate"] = reorder_fill_rate
        # For get_percentile / full_benchmark_report, pass collected metrics as dict
        if action in ("get_percentile", "full_benchmark_report") and len(p) > 1:
            metrics = {k: v for k, v in p.items() if k != "category"}
            p = {"metrics": metrics, "category": category}
        return await dispatch_domain("benchmark", action, p)

    # ── admin ─────────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_admin(
        action: str,
        label: str = "",
        rate_limit_rpm: int = 60,
        key_hash: str = "",
    ) -> str:
        """Admin domain — API key management and platform administration.

        action:
          issue_key        — generate a new Bearer API key for the current tenant
                             (plaintext shown once only; store securely)
          list_keys        — list all keys (hash prefix + metadata, no plaintext)
          revoke_key       — deactivate a key by its hash prefix
          rate_limit_status — check current requests/minute for a key
          platform_status  — admin overview: key count, auth mode, feature flags

        label: friendly name for the key (issue_key)
        rate_limit_rpm: max requests per minute for this key (issue_key, default 60; 0 = unlimited)
        key_hash: hash prefix from list_keys (revoke_key / rate_limit_status)

        Auth flow:
          1. Issue a key per tenant → they use it as Authorization: Bearer <key>
          2. The middleware auto-extracts tenant_id from the key record
          3. No need to pass tenant_id in each request once key is set up
        """
        return await dispatch_domain("admin", action, _p(label=label, key_hash=key_hash,
                                                          rate_limit_rpm=rate_limit_rpm))

    # ── inventory_pool ────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_inventory_pool(
        action: str,
        tenant_id: str = "",
        days: int = 7,
        platforms: str = "amazon,meli,tiktok",
        limit: int = 20,
        min_move_units: int = 5,
        min_delta_pct: float = 0.10,
        max_move_pct: float = 0.30,
        floor_units: int = 5,
        sku_filter: str = "",
        confirm: bool = False,
    ) -> str:
        """Inventory Pool Reconciliation domain (P4.2).

        Reads cross-platform inventory, computes velocity-weighted target allocations,
        and (optionally) queues rebalance write intents via command_center confirm gate.

        action:
          pool_status      — read-only health check: current vs recommended, skus needing rebalance
          allocation_plan  — full per-SKU plan with deltas (no writes)
          pool_reconcile   — queue write intents for adjustment (requires confirm=True in live mode)
          connection_status — P4.2 status and roadmap

        Key params:
          days           — lookback window for velocity calculation (default 7)
          platforms      — comma-separated list: amazon,meli,tiktok (default all three)
          min_move_units — minimum delta to trigger a move (default 5)
          min_delta_pct  — minimum delta % of current stock (default 0.10 = 10%)
          max_move_pct   — cap move at X% of total pool per run (default 0.30)
          floor_units    — minimum units to keep on each active platform (default 5)
          sku_filter     — comma-separated list to restrict reconcile scope
          confirm        — set True to queue writes (only in live mode; dry-run = always preview)

        Tier: global_suite (feat.inventory_pool)
        Writes go through command_center confirm gate — always confirm before executing.
        """
        return await dispatch_domain("inventory_pool", action, _p(
            tenant_id=tenant_id,
            days=days,
            platforms=platforms,
            limit=limit,
            min_move_units=min_move_units,
            min_delta_pct=min_delta_pct,
            max_move_pct=max_move_pct,
            floor_units=floor_units,
            sku_filter=sku_filter,
            confirm=confirm,
        ))

    # ── sync_schedule ─────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_sync_schedule(
        action: str,
        tenant_id: str = "",
        schedule_id: str = "",
        label: str = "",
        platforms: str = "",
        frequency_hint: str = "daily",
        min_move_units: int = 5,
        min_delta_pct: float = 0.10,
        max_move_pct: float = 0.30,
        floor_units: int = 5,
        sku_filter: str = "",
        confirm: bool = False,
        limit: int = 20,
        active: bool = True,
    ) -> str:
        """Sync Schedule domain — automated inventory reconciliation scheduling (P4.3).

        action:
          create_schedule    — save a sync configuration (thresholds, platforms, frequency intent)
          list_schedules     — list all schedules for this tenant
          delete_schedule    — remove a schedule by schedule_id
          trigger_now        — immediately run pool_reconcile with schedule config
                               (confirm=True required in live mode to queue writes)
          sync_history       — view recent sync run history with outcomes
          real_time_sync_info — Enterprise SOW upgrade information
          connection_status  — P4.3 status and roadmap

        Key params:
          schedule_id    — unique identifier for the schedule (default: sched_{tenant_id})
          label          — friendly name for the schedule
          platforms      — platforms to sync: amazon,meli,tiktok
          frequency_hint — intent label only (daily/hourly); actual scheduling via external cron
          min_move_units — minimum delta to trigger a move (default 5)
          min_delta_pct  — minimum delta % of stock (default 0.10)
          max_move_pct   — max units moved per run, as % of pool (default 0.30)
          floor_units    — minimum units to keep on each platform (default 5)
          sku_filter     — comma-separated SKUs to restrict scope
          confirm        — set True to queue writes (trigger_now only, live mode)
          limit          — max history entries to return (sync_history)
          active         — whether this schedule is active (create_schedule)

        Tier: global_suite (feat.sync_schedule)
        True real-time sub-minute sync requires Enterprise SOW — use real_time_sync_info.
        """
        return await dispatch_domain("sync_schedule", action, _p(
            tenant_id=tenant_id,
            schedule_id=schedule_id,
            label=label,
            platforms=platforms,
            frequency_hint=frequency_hint,
            min_move_units=min_move_units,
            min_delta_pct=min_delta_pct,
            max_move_pct=max_move_pct,
            floor_units=floor_units,
            sku_filter=sku_filter,
            confirm=confirm,
            limit=limit,
            active=active,
        ))

    # ── features ─────────────────────────────────────────────────────────────
    @mcp.tool()
    async def amazon_features(
        action: str,
        tier: str = "",
        feature_id: str = "",
    ) -> str:
        """Feature management — enable/disable modules per tenant for differentiated service.

        action:
          list_all          — show all features with enabled/disabled status and tier requirements
          get_tenant_config — current tier and enabled feature list for this tenant
          list_tiers        — available tiers (starter/standard/advanced/global_suite) with pricing
          set_tier          — set the service tier (changes which features are active)
          enable            — explicitly enable a single feature (adds on top of tier)
          disable           — explicitly disable a single feature (overrides tier)

        tier: target tier for set_tier (starter | standard | advanced | global_suite | all)
        feature_id: feature to toggle for enable/disable (e.g. feat.advertising)

        Tiers (cumulative):
          starter      → profit_tracking + inventory_management + orders + catalog + daily_briefing
          standard     → +aging_inventory + listing_health + alerts + pricing + reports + fulfillment
          advanced     → +advertising + brand_analytics + competitor_intel + notifications + fee_analysis
          global_suite → +listing_crud + cross_platform_ml + tiktok_sync

        Disabled features silently return {feature_disabled: true} instead of running.
        """
        return await dispatch_domain("features", action, _p(tier=tier, feature_id=feature_id))

    EXPORTS.update({
        "amazon_health": amazon_health,
        "amazon_system": amazon_system,
        "amazon_account": amazon_account,
        "amazon_catalog": amazon_catalog,
        "amazon_pricing": amazon_pricing,
        "amazon_orders": amazon_orders,
        "amazon_inventory": amazon_inventory,
        "amazon_listings": amazon_listings,
        "amazon_report": amazon_report,
        "amazon_ads": amazon_ads,
        "amazon_finance": amazon_finance,
        "amazon_fulfillment": amazon_fulfillment,
        "amazon_analytics": amazon_analytics,
        "amazon_alerts": amazon_alerts,
        "amazon_insights": amazon_insights,
        "amazon_notify": amazon_notify,
        "amazon_billing": amazon_billing,
        "amazon_features": amazon_features,
        "amazon_meli": amazon_meli,
        "amazon_tiktok": amazon_tiktok,
        "amazon_cross_platform": amazon_cross_platform,
        "amazon_rto_geo": amazon_rto_geo,
        "amazon_command_center": amazon_command_center,
        "amazon_benchmark": amazon_benchmark,
        "amazon_admin": amazon_admin,
        "amazon_inventory_pool": amazon_inventory_pool,
        "amazon_sync_schedule": amazon_sync_schedule,
    })
