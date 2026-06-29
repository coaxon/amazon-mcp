"""SP-API endpoint rate limit registry tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from amazon_mcp.clients.rate_limit import (
    SP_API_RATE_LIMITS,
    RateLimitRegistry,
    resolve_sp_endpoint_category,
    rate_limit_for_category,
)


@pytest.mark.parametrize(
    "endpoint_key,expected_category",
    [
        ("sp:/orders/v0/orders", "orders"),
        ("sp:/orders/v0/orders/123/orderItems", "orders"),
        ("sp:POST:/reports/2021-06-30/reports", "reports"),
        ("sp:/reports/2021-06-30/reports/R1", "reports"),
        ("sp:/fba/inventory/v1/summaries", "inventory"),
        ("sp:/products/pricing/v0/price", "products"),
        ("sp:/unknown/v9/foo", "default"),
    ],
)
def test_resolve_sp_endpoint_category(endpoint_key, expected_category):
    assert resolve_sp_endpoint_category(endpoint_key) == expected_category


def test_rate_limit_for_category_values():
    orders_rate, orders_burst = rate_limit_for_category("orders")
    reports_rate, reports_burst = rate_limit_for_category("reports")
    inv_rate, inv_burst = rate_limit_for_category("inventory")
    assert orders_rate == pytest.approx(1.0 / 60.0)
    assert orders_burst == 1
    assert reports_rate == pytest.approx(1.0 / 45.0)
    assert reports_burst == 1
    assert inv_rate == 2.0
    assert inv_burst == 5


def test_registry_shares_bucket_within_category():
    reg = RateLimitRegistry()
    b1 = reg.bucket("sp:/orders/v0/orders")
    b2 = reg.bucket("sp:/orders/v0/orders/ABC/orderItems")
    assert b1 is b2
    assert b1.rate == pytest.approx(SP_API_RATE_LIMITS["orders"][0])
    assert b1.burst == SP_API_RATE_LIMITS["orders"][1]


def test_registry_distinct_buckets_per_category():
    reg = RateLimitRegistry()
    orders = reg.bucket("sp:/orders/v0/orders")
    reports = reg.bucket("sp:POST:/reports/2021-06-30/reports")
    inventory = reg.bucket("sp:/fba/inventory/v1/summaries")
    assert orders is not reports is not inventory
    assert inventory.rate == 2.0
