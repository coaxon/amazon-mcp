from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from amazon_mcp.auth.lwa import LWAAuth
from amazon_mcp.clients.http_retry import raise_on_429
from amazon_mcp.clients.rate_limit import RateLimitRegistry
from amazon_mcp.clients.response_cache import ResponseCache, CACHE_MISS
from amazon_mcp.config import AmazonConfig

_ADS_BASE = "https://advertising-api.amazon.com"

# Reporting API v3 report type IDs
_ADS_REPORT_TYPES = {
    "sp_campaigns": "spCampaigns",
    "sp_keywords": "spKeywords",
    "sp_search_term": "spSearchTerm",
    "sp_advertised_product": "spAdvertisedProduct",
    "sp_targeting": "spTargeting",
    "sb_campaigns": "sbCampaigns",
    "sd_campaigns": "sdCampaigns",
}

_SP_COLUMNS = {
    "sp_campaigns": ["campaignId", "campaignName", "campaignStatus", "impressions", "clicks",
                     "cost", "purchases7d", "sales7d", "roas", "clickThroughRate", "costPerClick"],
    "sp_keywords": ["keywordId", "keywordText", "matchType", "campaignId", "adGroupId",
                    "impressions", "clicks", "cost", "purchases7d", "sales7d", "roas", "acos"],
    "sp_search_term": ["searchTerm", "campaignId", "adGroupId", "keywordId", "keywordText",
                       "matchType", "impressions", "clicks", "cost", "purchases7d",
                       "sales7d", "roas", "acos", "clickThroughRate"],
    "sp_advertised_product": ["campaignId", "adGroupId", "asin", "sku", "impressions", "clicks",
                               "cost", "purchases7d", "sales7d", "roas", "unitsSoldClicks7d"],
    "sb_campaigns": ["campaignId", "campaignName", "impressions", "clicks", "cost",
                     "purchases14d", "sales14d", "roas", "acos"],
    "sd_campaigns": ["campaignId", "campaignName", "impressions", "clicks", "cost",
                     "purchases14d", "sales14d", "roas"],
}

# groupBy dimension per report type (required by Ads API v3)
_REPORT_GROUP_BY: dict[str, list[str]] = {
    "sp_campaigns": ["campaign"],
    "sp_keywords": ["keyword"],
    "sp_search_term": ["searchTerm"],
    "sp_advertised_product": ["advertiser"],
    "sb_campaigns": ["campaign"],
    "sd_campaigns": ["campaign"],
}


class AdsAPIClient:
    """Amazon Advertising API v3 client — campaigns, keywords, reporting."""

    def __init__(self, cfg: AmazonConfig, auth: LWAAuth, limits: RateLimitRegistry) -> None:
        self.cfg = cfg
        self.auth = auth
        self.limits = limits
        self._cache = ResponseCache(ttl_seconds=cfg.cache_ttl_seconds)

    def _headers(self, token: str) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {token}",
            "Amazon-Advertising-API-ClientId": self.cfg.ads_client_id or self.cfg.lwa_client_id,
            "Content-Type": "application/json",
        }
        if self.cfg.ads_profile_id:
            h["Amazon-Advertising-API-Scope"] = self.cfg.ads_profile_id
        return h

    def _date(self, days_ago: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        async def _do() -> Any:
            token = await self.auth.get_access_token()
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.get(
                    f"{_ADS_BASE}{path}", params=params, headers=self._headers(token)
                )
                raise_on_429(resp)
                return resp.json()
        return await self.limits.call_with_backoff(f"ads:{path}", _do)

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        async def _do() -> Any:
            token = await self.auth.get_access_token()
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(
                    f"{_ADS_BASE}{path}", json=body, headers=self._headers(token)
                )
                raise_on_429(resp)
                return resp.json()
        return await self.limits.call_with_backoff(f"ads:POST:{path}", _do)

    async def _put(self, path: str, body: Any) -> Any:
        async def _do() -> Any:
            token = await self.auth.get_access_token()
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.put(
                    f"{_ADS_BASE}{path}", json=body, headers=self._headers(token)
                )
                raise_on_429(resp)
                return resp.json()
        return await self.limits.call_with_backoff(f"ads:PUT:{path}", _do)

    # ── Campaigns ─────────────────────────────────────────────────────────────

    async def list_campaigns(self, state_filter: str = "enabled") -> dict[str, Any]:
        """List Sponsored Products campaigns."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "campaigns": [
                    {"campaignId": "C001", "name": "SP-Auto-Main", "state": "enabled",
                     "dailyBudget": 50.0, "startDate": "2026-01-01", "targetingType": "AUTO"},
                    {"campaignId": "C002", "name": "SP-Manual-KW", "state": "enabled",
                     "dailyBudget": 30.0, "startDate": "2026-01-15", "targetingType": "MANUAL"},
                    {"campaignId": "C003", "name": "SP-Competitor", "state": "paused",
                     "dailyBudget": 25.0, "startDate": "2026-02-01", "targetingType": "MANUAL"},
                ],
                "count": 3,
            }
        params: dict[str, str] = {}
        if state_filter:
            params["stateFilter"] = state_filter
        data = await self._get("/v2/sp/campaigns", params)
        campaigns = data if isinstance(data, list) else data.get("campaigns", [])
        return {"ok": True, "count": len(campaigns), "campaigns": campaigns}

    async def pause_campaign(self, campaign_id: str) -> dict[str, Any]:
        """Set Sponsored Products campaign state to PAUSED (write action — B15)."""
        cid = str(campaign_id or "").strip()
        if not cid:
            return {"ok": False, "error": "campaign_id required"}
        if self.cfg.dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "campaignId": cid,
                "action": "PAUSED",
                "previous_state": "enabled",
                "new_state": "paused",
            }
        body = [{"campaignId": cid, "state": "PAUSED"}]
        data = await self._put("/sp/campaigns", body)
        return {
            "ok": True,
            "dry_run": False,
            "campaignId": cid,
            "action": "PAUSED",
            "raw": data,
        }

    async def list_ad_groups(self, campaign_id: str = "") -> dict[str, Any]:
        """List SP ad groups, optionally filtered by campaign."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "adGroups": [
                    {"adGroupId": "AG001", "campaignId": "C001", "name": "AdGroup-Auto", "state": "enabled",
                     "defaultBid": 1.20},
                    {"adGroupId": "AG002", "campaignId": "C002", "name": "AdGroup-Exact", "state": "enabled",
                     "defaultBid": 1.50},
                ],
                "count": 2,
            }
        params: dict[str, str] = {}
        if campaign_id:
            params["campaignIdFilter"] = campaign_id
        data = await self._get("/v2/sp/adGroups", params)
        groups = data if isinstance(data, list) else data.get("adGroups", [])
        return {"ok": True, "count": len(groups), "adGroups": groups}

    async def list_keywords(self, campaign_id: str = "", ad_group_id: str = "") -> dict[str, Any]:
        """List SP keywords with match types."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "keywords": [
                    {"keywordId": "KW001", "campaignId": "C002", "adGroupId": "AG002",
                     "keywordText": "mcp server python", "matchType": "EXACT", "state": "enabled", "bid": 1.50},
                    {"keywordId": "KW002", "campaignId": "C002", "adGroupId": "AG002",
                     "keywordText": "amazon api integration", "matchType": "PHRASE", "state": "enabled", "bid": 1.20},
                    {"keywordId": "KW003", "campaignId": "C002", "adGroupId": "AG002",
                     "keywordText": "amazon mcp", "matchType": "BROAD", "state": "enabled", "bid": 0.90},
                ],
                "count": 3,
            }
        params: dict[str, str] = {}
        if campaign_id:
            params["campaignIdFilter"] = campaign_id
        if ad_group_id:
            params["adGroupIdFilter"] = ad_group_id
        data = await self._get("/v2/sp/keywords", params)
        kws = data if isinstance(data, list) else data.get("keywords", [])
        return {"ok": True, "count": len(kws), "keywords": kws}

    # ── Reporting API v3 ──────────────────────────────────────────────────────

    async def create_report(self, report_type_key: str, days: int = 7, time_unit: str = "SUMMARY") -> dict[str, Any]:
        """Request an ads report via Reporting API v3."""
        report_type_id = _ADS_REPORT_TYPES.get(report_type_key, report_type_key)
        columns = _SP_COLUMNS.get(report_type_key, [
            "impressions", "clicks", "cost", "purchases7d", "sales7d", "roas"
        ])
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "reportId": "ADS-REPORT-DRY-001",
                "reportType": report_type_id,
                "status": "COMPLETED",
            }
        ad_product = "SPONSORED_PRODUCTS"
        if report_type_key.startswith("sb"):
            ad_product = "SPONSORED_BRANDS"
        elif report_type_key.startswith("sd"):
            ad_product = "SPONSORED_DISPLAY"

        group_by = _REPORT_GROUP_BY.get(report_type_key, ["campaign"])
        body = {
            "name": f"AmazonMCP_{report_type_key}_{days}d",
            "startDate": self._date(days),
            "endDate": self._date(0),
            "configuration": {
                "adProduct": ad_product,
                "columns": columns,
                "reportTypeId": report_type_id,
                "groupBy": group_by,
                "timeUnit": time_unit,
                "format": "GZIP_JSON",
            },
        }
        data = await self._post("/reporting/reports", body)
        return {
            "ok": True,
            "reportId": data.get("reportId"),
            "status": data.get("status"),
            "reportType": report_type_id,
        }

    async def get_report_status(self, report_id: str) -> dict[str, Any]:
        """Check ads report processing status."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "reportId": report_id,
                "status": "COMPLETED", "url": None,
            }
        data = await self._get(f"/reporting/reports/{report_id}")
        return {
            "ok": True,
            "reportId": report_id,
            "status": data.get("status"),
            "url": data.get("url"),
            "fileSize": data.get("fileSize"),
        }

    # ── Performance Summaries ─────────────────────────────────────────────────

    async def sponsored_ads_summary(self) -> dict[str, Any]:
        """Spend, sales, ROAS summary across all active campaigns."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "spend_usd": 312.44, "sales_usd": 1840.20, "roas": 5.89,
                "impressions": 48200, "clicks": 1340, "ctr": 0.028,
                "cpc": 0.233, "campaigns_active": 3, "acos": 0.170,
            }
        camps_resp = await self.list_campaigns("enabled")
        campaigns = camps_resp.get("campaigns", [])
        # Without report data, return campaign count + budget info
        total_budget = sum(c.get("dailyBudget", 0) for c in campaigns)
        return {
            "ok": True,
            "campaigns_active": len(campaigns),
            "total_daily_budget": total_budget,
            "note": "For full spend/sales data, use get_ads_performance_report.",
        }

    async def keyword_performance(self, campaign_id: str = "", days: int = 7) -> dict[str, Any]:
        """Keyword performance metrics."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "period_days": days,
                "keywords": [
                    {"keyword": "mcp server python", "matchType": "EXACT",
                     "impressions": 1200, "clicks": 84, "spend_usd": 42.10,
                     "sales_usd": 234.50, "acos": 0.180, "roas": 5.57},
                    {"keyword": "amazon api integration", "matchType": "PHRASE",
                     "impressions": 3400, "clicks": 190, "spend_usd": 89.30,
                     "sales_usd": 612.00, "acos": 0.146, "roas": 6.85},
                    {"keyword": "amazon mcp", "matchType": "BROAD",
                     "impressions": 890, "clicks": 32, "spend_usd": 14.40,
                     "sales_usd": 0, "acos": None, "roas": 0},
                ],
                "totals": {
                    "spend_usd": 145.80, "sales_usd": 846.50,
                    "acos": 0.172, "roas": 5.81,
                },
            }
        # Request keyword report
        report = await self.create_report("sp_keywords", days)
        return {
            "ok": True,
            "message": "Keyword report requested. Use get_report_status to check completion.",
            "reportId": report.get("reportId"),
            "period_days": days,
        }

    async def get_search_term_performance(self, days: int = 14) -> dict[str, Any]:
        """Search term report — which actual search terms triggered ads."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "period_days": days,
                "search_terms": [
                    {"term": "best mcp server for amazon", "impressions": 450, "clicks": 38,
                     "spend": 18.24, "sales": 142.50, "acos": 0.128, "conversion": 0.079},
                    {"term": "amazon sp api python library", "impressions": 210, "clicks": 22,
                     "spend": 9.90, "sales": 89.00, "acos": 0.111, "conversion": 0.091},
                    {"term": "amazon mcp integration tool", "impressions": 88, "clicks": 4,
                     "spend": 1.96, "sales": 0, "acos": None, "conversion": 0.0},
                ],
                "top_converting_term": "amazon sp api python library",
                "high_spend_no_sales": ["amazon mcp integration tool"],
            }
        report = await self.create_report("sp_search_term", days)
        return {
            "ok": True,
            "message": "Search term report requested.",
            "reportId": report.get("reportId"),
            "period_days": days,
        }

    async def get_campaign_performance(self, days: int = 7) -> dict[str, Any]:
        """Per-campaign performance breakdown."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "period_days": days,
                "campaigns": [
                    {"id": "C001", "name": "SP-Auto-Main", "status": "enabled",
                     "impressions": 22400, "clicks": 680, "spend": 142.80,
                     "sales": 890.50, "acos": 0.160, "roas": 6.24},
                    {"id": "C002", "name": "SP-Manual-KW", "status": "enabled",
                     "impressions": 18900, "clicks": 520, "spend": 124.40,
                     "sales": 742.00, "acos": 0.168, "roas": 5.97},
                    {"id": "C003", "name": "SP-Competitor", "status": "paused",
                     "impressions": 6900, "clicks": 140, "spend": 45.24,
                     "sales": 207.70, "acos": 0.218, "roas": 4.59},
                ],
                "account_totals": {
                    "impressions": 48200, "clicks": 1340,
                    "spend": 1020.00, "sales": 4480.00, "acos": 0.228, "roas": 4.39,
                },
            }
        _ck = f"campaign_perf:{days}"
        cached = self._cache.get(_ck)
        if cached is not CACHE_MISS:
            return cached
        report = await self.create_report("sp_campaigns", days)
        result = {
            "ok": True,
            "message": "Campaign report requested.",
            "reportId": report.get("reportId"),
            "period_days": days,
        }
        self._cache.set(_ck, result)
        return result

    async def get_product_ad_performance(self, days: int = 7) -> dict[str, Any]:
        """ASIN-level advertising performance."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "period_days": days,
                "products": [
                    {"asin": "B0FIXTURE01", "sku": "SKU-FIX-001",
                     "impressions": 28500, "clicks": 820, "spend": 540.00,
                     "sales": 3240.00, "units": 108, "acos": 0.167, "roas": 6.00},
                    {"asin": "B0FIXTURE02", "sku": "SKU-FIX-002",
                     "impressions": 19700, "clicks": 520, "spend": 480.00,
                     "sales": 1240.00, "units": 62, "acos": 0.387, "roas": 2.58},
                ],
            }
        report = await self.create_report("sp_advertised_product", days)
        return {
            "ok": True,
            "message": "Product ads report requested.",
            "reportId": report.get("reportId"),
            "period_days": days,
        }

    async def get_bid_recommendations(self, ad_group_id: str, asins: list[str] | None = None) -> dict[str, Any]:
        """Get bid recommendations for an ad group."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True, "adGroupId": ad_group_id,
                "recommendations": [
                    {"suggestedBid": 1.24, "rangeStart": 0.78, "rangeEnd": 2.14},
                ],
                "note": "Suggested bids based on auction data",
            }
        body: dict[str, Any] = {"adGroupId": ad_group_id}
        if asins:
            body["asins"] = asins[:10]
        data = await self._post("/v2/sp/targets/bidRecommendations", body)
        return {"ok": True, "adGroupId": ad_group_id, "recommendations": data}

    async def get_profile_info(self) -> dict[str, Any]:
        """Get advertising profile info (account type, marketplace, currency)."""
        if self.cfg.dry_run:
            return {
                "ok": True, "dry_run": True,
                "profileId": "1234567890",
                "countryCode": "US",
                "currencyCode": "USD",
                "timezone": "America/Los_Angeles",
                "accountType": "seller",
                "marketplace": "ATVPDKIKX0DER",
            }
        if not self.cfg.ads_profile_id:
            # List all profiles to find valid ones
            data = await self._get("/v2/profiles")
            profiles = data if isinstance(data, list) else []
            return {"ok": True, "profiles": profiles}
        data = await self._get(f"/v2/profiles/{self.cfg.ads_profile_id}")
        return {"ok": True, "profile": data}
