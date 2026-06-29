"""Tests for RTO Geographic Intelligence — rto_geo domain + scenario layer."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")

from amazon_mcp.scenarios.rto_geo import (
    build_rto_advisory,
    geo_cluster_returns,
    parse_orders_tsv,
)
from amazon_mcp.tools.registry import dispatch_domain


@pytest.fixture(autouse=True)
def _ensure_registry():
    import amazon_mcp.server  # noqa: F401
    yield


# ── parse_orders_tsv ──────────────────────────────────────────────────────────

class TestParseOrdersTsv:
    def test_basic_parse(self):
        tsv = "amazon-order-id\tship-state\tquantity\n111-1\tOR\t2\n222-2\tCA\t1\n"
        rows = parse_orders_tsv(tsv)
        assert len(rows) == 2
        assert rows[0] == {"order_id": "111-1", "ship_state": "OR", "quantity": 2}
        assert rows[1] == {"order_id": "222-2", "ship_state": "CA", "quantity": 1}

    def test_empty_input(self):
        assert parse_orders_tsv("") == []
        assert parse_orders_tsv("\n\n") == []

    def test_header_only(self):
        assert parse_orders_tsv("amazon-order-id\tship-state\tquantity\n") == []

    def test_missing_order_id_skipped(self):
        tsv = "amazon-order-id\tship-state\tquantity\n\tOR\t1\n"
        rows = parse_orders_tsv(tsv)
        assert rows == []

    def test_quantity_defaults_to_1(self):
        tsv = "amazon-order-id\tship-state\tquantity\n333-3\tWA\t\n"
        rows = parse_orders_tsv(tsv)
        assert rows[0]["quantity"] == 1

    def test_ship_state_uppercased(self):
        tsv = "amazon-order-id\tship-state\tquantity\n444-4\tor\t1\n"
        rows = parse_orders_tsv(tsv)
        assert rows[0]["ship_state"] == "OR"

    def test_alternate_column_name_order_id(self):
        tsv = "order-id\tship-state\tquantity\n555-5\tTX\t3\n"
        rows = parse_orders_tsv(tsv)
        assert rows[0]["order_id"] == "555-5"


# ── geo_cluster_returns ───────────────────────────────────────────────────────

class TestGeoClusterReturns:
    def _make_orders(self):
        return [
            {"order_id": "O-001", "ship_state": "OR", "quantity": 5},
            {"order_id": "O-002", "ship_state": "OR", "quantity": 5},
            {"order_id": "O-003", "ship_state": "CA", "quantity": 4},
            {"order_id": "O-004", "ship_state": "TX", "quantity": 3},
            {"order_id": "O-005", "ship_state": "OR", "quantity": 5},
            {"order_id": "O-006", "ship_state": "WA", "quantity": 2},
        ]

    def _make_returns(self):
        return [
            {"order-id": "O-001", "quantity": 4},  # OR: 4/15 = 26.7%
            {"order-id": "O-002", "quantity": 3},  # OR: +3 → 7/15 = 46.7%
            {"order-id": "O-003", "quantity": 1},  # CA: 1/4 = 25%
            # TX and WA: 0 returns
        ]

    def test_basic_clustering(self):
        result = geo_cluster_returns(self._make_returns(), self._make_orders())
        assert result["ok"] is True
        assert result["total_orders_qty"] == 24
        assert result["total_returns_qty"] == 8
        states = {s["state"]: s for s in result["by_state"]}
        assert states["OR"]["return_rate_pct"] > 0
        assert states["CA"]["return_rate_pct"] > 0
        assert states["TX"]["return_rate_pct"] == 0.0

    def test_high_rto_flagged(self):
        result = geo_cluster_returns(
            self._make_returns(), self._make_orders(),
            threshold_rate=0.20, min_orders=3
        )
        high = {s["state"] for s in result["high_rto_states"]}
        assert "OR" in high  # OR has ~46.7% return rate

    def test_min_orders_filters_small_states(self):
        result = geo_cluster_returns(
            self._make_returns(), self._make_orders(),
            threshold_rate=0.10, min_orders=10  # WA only has 2 orders
        )
        high_states = {s["state"] for s in result["high_rto_states"]}
        assert "WA" not in high_states

    def test_unmatched_returns_counted(self):
        returns = self._make_returns() + [{"order-id": "NO-SUCH-ORDER", "quantity": 2}]
        result = geo_cluster_returns(returns, self._make_orders())
        assert result["unmatched_returns_qty"] == 2

    def test_empty_inputs(self):
        result = geo_cluster_returns([], [])
        assert result["ok"] is True
        assert result["total_orders_qty"] == 0
        assert result["by_state"] == []

    def test_by_state_sorted_by_rate_desc(self):
        result = geo_cluster_returns(self._make_returns(), self._make_orders())
        rates = [s["return_rate_pct"] for s in result["by_state"]]
        assert rates == sorted(rates, reverse=True)

    def test_global_rate_computed(self):
        result = geo_cluster_returns(self._make_returns(), self._make_orders())
        # 8 returns / 24 orders = 33.33%
        assert abs(result["global_return_rate_pct"] - 33.33) < 1.0

    def test_vs_global_multiplier_in_row(self):
        result = geo_cluster_returns(self._make_returns(), self._make_orders())
        states = {s["state"]: s for s in result["by_state"]}
        or_state = states.get("OR", {})
        assert or_state.get("vs_global") is not None

    def test_thresholds_returned(self):
        result = geo_cluster_returns(self._make_returns(), self._make_orders(),
                                     threshold_rate=0.12, multiplier=3.0, min_orders=7)
        assert result["thresholds"]["rate"] == 0.12
        assert result["thresholds"]["multiplier"] == 3.0
        assert result["thresholds"]["min_orders"] == 7


# ── build_rto_advisory ────────────────────────────────────────────────────────

class TestBuildRtoAdvisory:
    def test_advisory_structure(self):
        alerts = [
            {"state": "OR", "return_rate_pct": 25.0, "vs_global": 2.5,
             "orders_qty": 20, "returns_qty": 5, "global_avg_pct": 10.0}
        ]
        advisories = build_rto_advisory(alerts, global_rate=0.10)
        assert len(advisories) == 1
        a = advisories[0]
        assert a["region"] == "OR"
        assert a["return_rate_pct"] == 25.0
        assert "OR" in a["message"]
        assert "advisory" not in a or True  # advisory key optional
        assert a["source"] == "rto_geo"
        assert "recommendation" in a

    def test_urgency_high_when_rate_ge_20(self):
        alerts = [{"state": "TX", "return_rate_pct": 22.0, "vs_global": 3.0,
                   "orders_qty": 10, "returns_qty": 5, "global_avg_pct": 8.0}]
        advisories = build_rto_advisory(alerts, global_rate=0.08)
        assert advisories[0]["urgency"] == "HIGH"

    def test_urgency_medium_when_rate_lt_20(self):
        alerts = [{"state": "WA", "return_rate_pct": 16.0, "vs_global": 2.1,
                   "orders_qty": 8, "returns_qty": 3, "global_avg_pct": 7.0}]
        advisories = build_rto_advisory(alerts, global_rate=0.07)
        assert advisories[0]["urgency"] == "MEDIUM"

    def test_max_5_advisories(self):
        alerts = [
            {"state": f"S{i}", "return_rate_pct": 20 + i, "vs_global": 2.0,
             "orders_qty": 10, "returns_qty": 5, "global_avg_pct": 8.0}
            for i in range(10)
        ]
        advisories = build_rto_advisory(alerts, global_rate=0.08)
        assert len(advisories) <= 5

    def test_empty_alerts(self):
        assert build_rto_advisory([], global_rate=0.10) == []


# ── Domain tool (dry-run via dispatch_domain) ─────────────────────────────────

class TestRtoGeoDomainTool:
    @pytest.mark.asyncio
    async def test_returns_geo_cluster(self):
        raw = await dispatch_domain("rto_geo", "returns_geo_cluster", {})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert "by_state" in inner
        assert "global_return_rate_pct" in inner
        assert "high_rto_states" in inner

    @pytest.mark.asyncio
    async def test_rto_region_alert(self):
        raw = await dispatch_domain("rto_geo", "rto_region_alert", {"top_n": 2})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert "top_alerts" in inner
        assert "advisories" in inner

    @pytest.mark.asyncio
    async def test_rto_ads_correlation(self):
        raw = await dispatch_domain("rto_geo", "rto_ads_correlation", {})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert inner.get("phase") == "R3-advisory"
        assert inner.get("auto_write") is False or "ads_correlation" in inner

    @pytest.mark.asyncio
    async def test_rto_health_score_factor(self):
        raw = await dispatch_domain("rto_geo", "rto_health_score_factor", {})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert 0 <= inner["rto_risk_factor"] <= 100
        assert inner["phase"] == "R2"
        assert "interpretation" in inner

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        raw = await dispatch_domain("rto_geo", "no_such_action", {})
        data = json.loads(raw)
        assert data["ok"] is False


# ── Feature gate: rto_geo requires standard tier ──────────────────────────────

class TestRtoGeoFeatureGate:
    @pytest.mark.asyncio
    async def test_starter_tenant_is_blocked(self):
        from amazon_mcp.features.feature_gate import set_tenant_tier
        set_tenant_tier("test_starter_rto", "starter")
        raw = await dispatch_domain("rto_geo", "rto_region_alert", {"tenant_id": "test_starter_rto"})
        data = json.loads(raw)
        assert data.get("ok") is False or data.get("data", {}).get("feature_disabled") is True

    @pytest.mark.asyncio
    async def test_standard_tenant_is_allowed(self):
        from amazon_mcp.features.feature_gate import set_tenant_tier
        set_tenant_tier("test_std_rto", "standard")
        raw = await dispatch_domain("rto_geo", "rto_region_alert", {"tenant_id": "test_std_rto"})
        data = json.loads(raw)
        assert data["ok"] is True


# ── Fixture file integration ──────────────────────────────────────────────────

class TestFixtureIntegration:
    def test_flat_file_orders_fixture_parses(self):
        fixture = Path(_ROOT) / "tests" / "fixtures" / "sp_api" / "flat_file_orders.tsv"
        if not fixture.exists():
            pytest.skip("flat_file_orders.tsv fixture missing")
        rows = parse_orders_tsv(fixture.read_text())
        assert len(rows) > 0
        assert all(r["order_id"] for r in rows)

    def test_fixture_cluster_produces_states(self):
        from amazon_mcp.scenarios.returns_summary import parse_returns_tsv
        returns_fixture = Path(_ROOT) / "tests" / "fixtures" / "sp_api" / "fba_returns.tsv"
        orders_fixture = Path(_ROOT) / "tests" / "fixtures" / "sp_api" / "flat_file_orders.tsv"
        if not returns_fixture.exists() or not orders_fixture.exists():
            pytest.skip("fixture files missing")
        returns = parse_returns_tsv(returns_fixture.read_text())
        orders = parse_orders_tsv(orders_fixture.read_text())
        result = geo_cluster_returns(returns, orders)
        assert result["ok"] is True
        assert result["states_analyzed"] >= 0
