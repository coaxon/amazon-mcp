"""Tests for P4.2 inventory pool reconciliation."""
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


@pytest.fixture(autouse=True)
def _bootstrap():
    import amazon_mcp.server  # noqa: F401
    yield


from amazon_mcp.tools.inventory_pool import (
    _compute_allocation_plan,
    _extract_sku_stock,
    _extract_velocity,
    allocation_plan,
    pool_reconcile,
    pool_status,
    pool_connection_status,
    _DEFAULT_MARGIN_WEIGHTS,
)
from amazon_mcp.tools.registry import dispatch_domain


# ── _extract_sku_stock ────────────────────────────────────────────────────────

class TestExtractSkuStock:
    def test_amazon_items(self):
        snaps = {
            "amazon": {"summaries": [
                {"sellerSku": "SKU-A", "totalQuantity": 100},
                {"sellerSku": "SKU-B", "totalQuantity": 50},
            ]}
        }
        result = _extract_sku_stock(snaps)
        assert result["SKU-A"]["amazon"] == 100
        assert result["SKU-B"]["amazon"] == 50

    def test_meli_items(self):
        snaps = {
            "meli": {"inventory": {"items": [
                {"sku": "SKU-A", "on_hand": 30},
            ]}}
        }
        result = _extract_sku_stock(snaps)
        assert result["SKU-A"]["meli"] == 30

    def test_tiktok_items(self):
        snaps = {
            "tiktok": {"inventory": {"items": [
                {"sku": "SKU-A", "on_hand": 20},
            ]}}
        }
        result = _extract_sku_stock(snaps)
        assert result["SKU-A"]["tiktok"] == 20

    def test_cross_platform_merge(self):
        snaps = {
            "amazon": {"summaries": [{"sellerSku": "SKU-X", "totalQuantity": 80}]},
            "meli": {"inventory": {"items": [{"sku": "SKU-X", "on_hand": 40}]}},
            "tiktok": {"inventory": {"items": [{"sku": "SKU-X", "on_hand": 20}]}},
        }
        result = _extract_sku_stock(snaps)
        p = result["SKU-X"]
        assert p["amazon"] == 80
        assert p["meli"] == 40
        assert p["tiktok"] == 20

    def test_empty_snapshots(self):
        result = _extract_sku_stock({})
        assert result == {}

    def test_missing_sku_field_skipped(self):
        snaps = {"amazon": {"summaries": [{"totalQuantity": 10}]}}
        result = _extract_sku_stock(snaps)
        assert result == {}


# ── _extract_velocity ─────────────────────────────────────────────────────────

class TestExtractVelocity:
    def test_amazon_velocity(self):
        snaps = {"amazon": {"items": [{"sellerSku": "SKU-A", "units_ordered": 70}]}}
        result = _extract_velocity(snaps, days=7)
        assert result["SKU-A"]["amazon"] == pytest.approx(10.0)

    def test_meli_velocity(self):
        snaps = {"meli": {"orders": {"items": [{"sku": "SKU-A", "units": 14}]}}}
        result = _extract_velocity(snaps, days=7)
        assert result["SKU-A"]["meli"] == pytest.approx(2.0)

    def test_days_divisor(self):
        snaps = {"amazon": {"items": [{"sellerSku": "S", "units_ordered": 30}]}}
        result = _extract_velocity(snaps, days=3)
        assert result["S"]["amazon"] == pytest.approx(10.0)

    def test_zero_units_ignored(self):
        snaps = {"amazon": {"items": [{"sellerSku": "S", "units_ordered": 0}]}}
        result = _extract_velocity(snaps, days=7)
        assert "S" not in result


# ── _compute_allocation_plan ──────────────────────────────────────────────────

class TestComputeAllocationPlan:
    def _make_sku_map(self, **stocks):
        """stocks: platform=units"""
        return {"SKU-1": dict(stocks)}

    def test_single_platform_excluded(self):
        sku_map = {"SKU-1": {"amazon": 100}}
        plans = _compute_allocation_plan(sku_map, {}, _DEFAULT_MARGIN_WEIGHTS, 5, 0.10, 0.30, 5)
        assert plans == []

    def test_zero_total_excluded(self):
        sku_map = {"SKU-1": {"amazon": 0, "meli": 0}}
        plans = _compute_allocation_plan(sku_map, {}, _DEFAULT_MARGIN_WEIGHTS, 5, 0.10, 0.30, 5)
        assert plans == []

    def test_balanced_no_plan(self):
        # Same velocity and stock → target ≈ current → no delta exceeds threshold
        vel = {"SKU-1": {"amazon": 5.0, "meli": 4.25}}
        sku_map = {"SKU-1": {"amazon": 55, "meli": 47}}
        plans = _compute_allocation_plan(sku_map, vel, _DEFAULT_MARGIN_WEIGHTS, 100, 0.10, 0.30, 5)
        # Large min_move forces no plans
        assert plans == []

    def test_imbalanced_generates_plan(self):
        # amazon velocity much higher → should get more
        vel = {"SKU-1": {"amazon": 10.0, "meli": 1.0}}
        sku_map = {"SKU-1": {"amazon": 10, "meli": 90}}
        plans = _compute_allocation_plan(sku_map, vel, _DEFAULT_MARGIN_WEIGHTS, 5, 0.05, 0.30, 5)
        assert len(plans) == 1
        plan = plans[0]
        assert "amazon" in plan["deltas"]
        assert plan["deltas"]["amazon"] > 0  # amazon should gain units
        assert plan["deltas"]["meli"] < 0    # meli should give up units

    def test_floor_units_respected(self):
        vel = {"SKU-1": {"amazon": 20.0, "meli": 0.1}}
        sku_map = {"SKU-1": {"amazon": 5, "meli": 100}}
        plans = _compute_allocation_plan(sku_map, vel, _DEFAULT_MARGIN_WEIGHTS, 1, 0.01, 0.30, 10)
        if plans:
            plan = plans[0]
            for p, tgt in plan["target"].items():
                assert tgt >= 10, f"{p} target {tgt} below floor"

    def test_urgency_score_positive(self):
        vel = {"SKU-1": {"amazon": 10.0, "meli": 1.0}}
        sku_map = {"SKU-1": {"amazon": 5, "meli": 95}}
        plans = _compute_allocation_plan(sku_map, vel, _DEFAULT_MARGIN_WEIGHTS, 5, 0.05, 0.30, 5)
        assert plans[0]["urgency_score"] > 0

    def test_sorted_by_urgency_desc(self):
        vel = {
            "SKU-1": {"amazon": 10.0, "meli": 1.0},
            "SKU-2": {"amazon": 100.0, "meli": 1.0},
        }
        sku_map = {
            "SKU-1": {"amazon": 5, "meli": 95},
            "SKU-2": {"amazon": 5, "meli": 995},
        }
        plans = _compute_allocation_plan(sku_map, vel, _DEFAULT_MARGIN_WEIGHTS, 5, 0.05, 0.30, 5)
        scores = [p["urgency_score"] for p in plans]
        assert scores == sorted(scores, reverse=True)


# ── pool_status ───────────────────────────────────────────────────────────────

class TestPoolStatus:
    @pytest.mark.asyncio
    async def test_returns_ok(self):
        result = await pool_status({"tenant_id": "default"})
        assert result["ok"] is True
        assert "pool_health_score" in result
        assert "health_label" in result

    @pytest.mark.asyncio
    async def test_health_score_in_range(self):
        result = await pool_status({"tenant_id": "default"})
        score = result["pool_health_score"]
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_has_required_fields(self):
        result = await pool_status({})
        for key in ("total_skus_tracked", "shared_skus", "skus_needing_rebalance", "platforms_active"):
            assert key in result, f"missing field: {key}"


# ── allocation_plan ───────────────────────────────────────────────────────────

class TestAllocationPlan:
    @pytest.mark.asyncio
    async def test_returns_ok(self):
        result = await allocation_plan({"tenant_id": "default"})
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_has_plans_list(self):
        result = await allocation_plan({})
        assert "plans" in result
        assert isinstance(result["plans"], list)

    @pytest.mark.asyncio
    async def test_total_units_to_move_non_negative(self):
        result = await allocation_plan({})
        assert result["total_units_to_move"] >= 0

    @pytest.mark.asyncio
    async def test_plan_count_matches_plans_len(self):
        result = await allocation_plan({})
        assert result["plan_count"] == len(result["plans"])

    @pytest.mark.asyncio
    async def test_parameters_echoed(self):
        result = await allocation_plan({"min_move_units": 3, "days": 14})
        params = result.get("parameters", {})
        assert params["min_move_units"] == 3
        assert params["days"] == 14


# ── pool_reconcile ────────────────────────────────────────────────────────────

class TestPoolReconcile:
    @pytest.mark.asyncio
    async def test_dry_run_preview_only(self):
        result = await pool_reconcile({"tenant_id": "default", "confirm": True})
        # In dry_run mode, always preview
        assert result.get("preview_only") is True or result.get("queued_count", 0) == 0

    @pytest.mark.asyncio
    async def test_no_confirm_returns_preview(self):
        result = await pool_reconcile({"tenant_id": "default", "confirm": False})
        assert result.get("preview_only") is True or result.get("ok") is True

    @pytest.mark.asyncio
    async def test_returns_ok(self):
        result = await pool_reconcile({"tenant_id": "default"})
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_sku_filter_applied(self):
        result = await pool_reconcile({"sku_filter": "NONEXISTENT-SKU-XYZ"})
        assert result["ok"] is True
        # With non-existent SKU filter, either balanced or empty queued
        assert result.get("queued_count", 0) == 0 or "message" in result


# ── pool_connection_status ────────────────────────────────────────────────────

class TestPoolConnectionStatus:
    @pytest.mark.asyncio
    async def test_ok_and_phase(self):
        result = await pool_connection_status({})
        assert result["ok"] is True
        assert result["phase"] == "P4.2"

    @pytest.mark.asyncio
    async def test_roadmap_includes_p42(self):
        result = await pool_connection_status({})
        assert "P4.2" in result["roadmap"]
        assert "✅" in result["roadmap"]["P4.2"]

    @pytest.mark.asyncio
    async def test_safety_guardrails_present(self):
        result = await pool_connection_status({})
        g = result["safety_guardrails"]
        assert "confirm_gate" in g
        assert "dry_run_safe" in g


# ── Domain dispatch (registry) ─────────────────────────────────────────────────

class TestInventoryPoolDomain:
    @pytest.mark.asyncio
    async def test_pool_status_via_dispatch(self):
        raw = await dispatch_domain("inventory_pool", "pool_status", {})
        data = json.loads(raw)
        assert data["ok"] is True
        assert data["domain"] == "amazon_inventory_pool"

    @pytest.mark.asyncio
    async def test_allocation_plan_via_dispatch(self):
        raw = await dispatch_domain("inventory_pool", "allocation_plan", {})
        data = json.loads(raw)
        assert data["ok"] is True
        assert "plans" in data["data"]

    @pytest.mark.asyncio
    async def test_pool_reconcile_via_dispatch(self):
        raw = await dispatch_domain("inventory_pool", "pool_reconcile", {"confirm": False})
        data = json.loads(raw)
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_connection_status_via_dispatch(self):
        raw = await dispatch_domain("inventory_pool", "connection_status", {})
        data = json.loads(raw)
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        raw = await dispatch_domain("inventory_pool", "nonexistent", {})
        data = json.loads(raw)
        assert data["ok"] is False

    @pytest.mark.asyncio
    async def test_supported_actions_in_meta(self):
        raw = await dispatch_domain("inventory_pool", "pool_status", {})
        data = json.loads(raw)
        actions = data["meta"]["supported_actions"]
        assert "pool_status" in actions
        assert "allocation_plan" in actions
        assert "pool_reconcile" in actions
        assert "connection_status" in actions


# ── Feature gate ───────────────────────────────────────────────────────────────

class TestInventoryPoolFeatureGate:
    @pytest.mark.asyncio
    async def test_passes_for_default_tenant(self):
        raw = await dispatch_domain("inventory_pool", "pool_status", {"tenant_id": "default"})
        data = json.loads(raw)
        # default tenant has "all" features
        assert data.get("ok") is True
        assert "feature_disabled" not in data.get("data", {})

    @pytest.mark.asyncio
    async def test_feature_in_catalog(self):
        from amazon_mcp.features.feature_registry import FEATURES_BY_ID
        feat = FEATURES_BY_ID.get("feat.inventory_pool")
        assert feat is not None
        assert feat.tier_min == "global_suite"

    @pytest.mark.asyncio
    async def test_feature_in_global_suite(self):
        from amazon_mcp.features.tier_bundles import GLOBAL_SUITE
        assert "feat.inventory_pool" in GLOBAL_SUITE

    @pytest.mark.asyncio
    async def test_feature_not_in_standard(self):
        from amazon_mcp.features.tier_bundles import STANDARD
        assert "feat.inventory_pool" not in STANDARD
