"""Tests for Feature C: SP-API Notifications expansion (listings status, issues, pricing health)."""
from __future__ import annotations

import asyncio
import json
import os
import pytest

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")

import amazon_mcp.server as _srv
from amazon_mcp.tools.domain_tools import EXPORTS
from amazon_mcp.integrations.sp_notifications import (
    parse_listings_item_status_change,
    parse_listings_item_issues_change,
    parse_pricing_health,
    parse_notification_payload,
    NOTIFICATION_TYPE_LISTINGS_STATUS,
    NOTIFICATION_TYPE_LISTINGS_ISSUES,
    NOTIFICATION_TYPE_PRICING_HEALTH,
)


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    _srv._reset_ctx_cache()


def _call(coro):
    return json.loads(asyncio.run(coro))


def _inner(raw: dict) -> dict:
    return raw.get("data", raw)


# ── subscribe actions ─────────────────────────────────────────────────────────

class TestSubscribeListingsStatus:
    def test_returns_ok(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account("subscribe_listings_status"))
        assert raw["ok"] is True

    def test_contains_notification_type(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account("subscribe_listings_status"))
        inner = _inner(raw)
        assert "LISTINGS_ITEM_STATUS_CHANGE" in (inner.get("notificationType") or "")

    def test_dry_run_flag(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account("subscribe_listings_status"))
        inner = _inner(raw)
        assert inner.get("dry_run") is True

    def test_custom_webhook_url(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account("subscribe_listings_status", webhook_url="https://myapp.example.com/hooks/listings"))
        assert raw["ok"] is True


class TestSubscribeListingsIssues:
    def test_returns_ok(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account("subscribe_listings_issues"))
        assert raw["ok"] is True

    def test_contains_notification_type(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account("subscribe_listings_issues"))
        inner = _inner(raw)
        assert "LISTINGS_ITEM_ISSUES_CHANGE" in (inner.get("notificationType") or "")


class TestSubscribePricingHealth:
    def test_returns_ok(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account("subscribe_pricing_health"))
        assert raw["ok"] is True

    def test_contains_notification_type(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account("subscribe_pricing_health"))
        inner = _inner(raw)
        assert "PRICING_HEALTH" in (inner.get("notificationType") or "")


# ── unsubscribe ───────────────────────────────────────────────────────────────

class TestUnsubscribe:
    def test_unsubscribe_success_dry_run(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account(
            "unsubscribe",
            notification_type="LISTINGS_ITEM_STATUS_CHANGE",
            subscription_id="SUB-DRY-001",
        ))
        assert raw["ok"] is True
        inner = _inner(raw)
        assert inner.get("status") == "deleted"

    def test_unsubscribe_missing_params_returns_error(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account("unsubscribe"))
        inner = _inner(raw)
        assert inner.get("ok") is False
        assert "error" in inner


# ── subscription_status ───────────────────────────────────────────────────────

class TestSubscriptionStatus:
    def test_returns_all_types(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account("subscription_status"))
        inner = _inner(raw)
        assert inner["ok"] is True
        assert inner["types_checked"] >= 5
        type_names = [s["type"] for s in inner["summary"]]
        assert "LISTINGS_ITEM_STATUS_CHANGE" in type_names
        assert "LISTINGS_ITEM_ISSUES_CHANGE" in type_names
        assert "PRICING_HEALTH" in type_names

    def test_filter_by_notification_type(self):
        amazon_account = EXPORTS["amazon_account"]
        raw = _call(amazon_account("subscription_status", notification_type="PRICING_HEALTH"))
        inner = _inner(raw)
        assert inner["ok"] is True
        assert inner["types_checked"] == 1
        assert inner["summary"][0]["type"] == "PRICING_HEALTH"


# ── notification payload parsers ──────────────────────────────────────────────

class TestListingsStatusParser:
    def _sample_payload(self, status="INACTIVE", asin="B0TEST001", sku="SKU-TEST-001"):
        return {
            "notificationType": "LISTINGS_ITEM_STATUS_CHANGE",
            "detail": {
                "ListingsItemStatusChangeNotification": {
                    "Asin": asin,
                    "SellerSKU": sku,
                    "MarketplaceId": "ATVPDKIKX0DER",
                    "Status": status,
                }
            },
        }

    def test_basic_parse(self):
        result = parse_listings_item_status_change(self._sample_payload())
        assert result["ok"] is True
        assert result["notification_type"] == NOTIFICATION_TYPE_LISTINGS_STATUS
        assert result["asin"] == "B0TEST001"
        assert result["sku"] == "SKU-TEST-001"
        assert result["status"] == "INACTIVE"

    def test_dispatched_via_generic_parser(self):
        result = parse_notification_payload(self._sample_payload())
        assert result["notification_type"] == NOTIFICATION_TYPE_LISTINGS_STATUS
        assert result["ok"] is True

    def test_field_snapshot_present(self):
        result = parse_listings_item_status_change(self._sample_payload())
        assert "status" in result["field_snapshot"]
        assert "sku" in result["field_snapshot"]


class TestListingsIssuesParser:
    def _sample_payload(self):
        return {
            "notificationType": "LISTINGS_ITEM_ISSUES_CHANGE",
            "detail": {
                "ListingsItemIssuesChangeNotification": {
                    "Asin": "B0TEST002",
                    "SellerSKU": "SKU-002",
                    "MarketplaceId": "ATVPDKIKX0DER",
                    "Issues": [
                        {"code": "MISSING_BULLET_POINTS", "severity": "ERROR", "message": "At least 3 bullet points required"},
                        {"code": "IMAGE_TOO_SMALL", "severity": "WARNING", "message": "Main image below 1000x1000px"},
                    ],
                }
            },
        }

    def test_basic_parse(self):
        result = parse_listings_item_issues_change(self._sample_payload())
        assert result["ok"] is True
        assert result["notification_type"] == NOTIFICATION_TYPE_LISTINGS_ISSUES
        assert result["asin"] == "B0TEST002"
        assert result["issue_count"] == 2
        assert len(result["issues"]) == 2

    def test_dispatched_via_generic_parser(self):
        result = parse_notification_payload(self._sample_payload())
        assert result["notification_type"] == NOTIFICATION_TYPE_LISTINGS_ISSUES

    def test_snapshot_has_issue_count(self):
        result = parse_listings_item_issues_change(self._sample_payload())
        assert result["field_snapshot"]["issue_count"] == 2


class TestPricingHealthParser:
    def _sample_payload(self, issue="PRICE_TOO_HIGH"):
        return {
            "notificationType": "PRICING_HEALTH",
            "detail": {
                "PricingHealthNotification": {
                    "Asin": "B0TEST003",
                    "SellerSKU": "SKU-003",
                    "MarketplaceId": "ATVPDKIKX0DER",
                    "Issue": issue,
                    "CompetitivePrice": 29.99,
                    "ReferencePrice": 34.99,
                }
            },
        }

    def test_basic_parse(self):
        result = parse_pricing_health(self._sample_payload())
        assert result["ok"] is True
        assert result["notification_type"] == NOTIFICATION_TYPE_PRICING_HEALTH
        assert result["asin"] == "B0TEST003"
        assert result["issue"] == "PRICE_TOO_HIGH"
        assert result["competitive_price"] == 29.99

    def test_dispatched_via_generic_parser(self):
        result = parse_notification_payload(self._sample_payload())
        assert result["notification_type"] == NOTIFICATION_TYPE_PRICING_HEALTH

    def test_reference_price_included(self):
        result = parse_pricing_health(self._sample_payload())
        assert result["reference_price"] == 34.99
