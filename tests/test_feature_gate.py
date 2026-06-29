"""Tests for feature gate — per-tenant enablement, tier bundles, and domain/action gating."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")
os.environ.setdefault("AMAZON_MCP_DEFAULT_TIER", "all")

import amazon_mcp.server as _srv
from amazon_mcp.features.feature_registry import ACTION_FEATURE_MAP, FEATURE_CATALOG, FEATURES_BY_ID
from amazon_mcp.features.tier_bundles import ADVANCED, GLOBAL_SUITE, STANDARD, STARTER, TIER_MAP, resolve_features
from amazon_mcp.features.feature_gate import FeatureDisabledError, FeatureGate, get_gate
from amazon_mcp.tools.domain_tools import EXPORTS


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    monkeypatch.setenv("AMAZON_MCP_DEFAULT_TIER", "all")
    _srv._reset_ctx_cache()


def _call(coro):
    return json.loads(asyncio.run(coro))


def _inner(raw: dict) -> dict:
    return raw.get("data", raw)


# ── Feature Registry ─────────────────────────────────────────────────────────

class TestFeatureRegistry:
    def test_all_features_have_unique_ids(self):
        ids = [f.feature_id for f in FEATURE_CATALOG]
        assert len(ids) == len(set(ids))

    def test_features_by_id_complete(self):
        for f in FEATURE_CATALOG:
            assert f.feature_id in FEATURES_BY_ID

    def test_action_feature_map_populated(self):
        assert len(ACTION_FEATURE_MAP) > 10

    def test_known_action_mapped(self):
        assert ACTION_FEATURE_MAP[("finance", "financial_summary")] == "feat.profit_tracking"
        assert ACTION_FEATURE_MAP[("inventory", "levels")] == "feat.inventory_management"
        assert ACTION_FEATURE_MAP[("ads", "campaign_list")] == "feat.advertising"
        assert ACTION_FEATURE_MAP[("listings", "update_price")] == "feat.listing_crud"
        assert ACTION_FEATURE_MAP[("report", "brand_analytics")] == "feat.brand_analytics"

    def test_system_actions_not_gated(self):
        assert ("system", "health") not in ACTION_FEATURE_MAP
        assert ("billing", "check_quota") not in ACTION_FEATURE_MAP

    def test_tier_min_values_valid(self):
        valid_tiers = {"starter", "standard", "advanced", "global_suite"}
        for f in FEATURE_CATALOG:
            assert f.tier_min in valid_tiers, f"{f.feature_id} has invalid tier_min={f.tier_min!r}"


# ── Tier Bundles ─────────────────────────────────────────────────────────────

class TestTierBundles:
    def test_cumulative_tiers(self):
        assert STARTER.issubset(STANDARD)
        assert STANDARD.issubset(ADVANCED)
        assert ADVANCED.issubset(GLOBAL_SUITE)

    def test_starter_has_core_features(self):
        assert "feat.profit_tracking" in STARTER
        assert "feat.inventory_management" in STARTER
        assert "feat.daily_briefing" in STARTER

    def test_standard_adds_aging_and_alerts(self):
        assert "feat.aging_inventory" in STANDARD
        assert "feat.alerts" in STANDARD
        assert "feat.fulfillment_fba" in STANDARD

    def test_advanced_adds_ads_and_analytics(self):
        assert "feat.advertising" in ADVANCED
        assert "feat.brand_analytics" in ADVANCED
        assert "feat.notifications" in ADVANCED

    def test_global_suite_adds_listing_crud_and_cross_platform(self):
        assert "feat.listing_crud" in GLOBAL_SUITE
        assert "feat.cross_platform_ml" in GLOBAL_SUITE
        assert "feat.tiktok_sync" in GLOBAL_SUITE

    def test_advertising_not_in_starter(self):
        assert "feat.advertising" not in STARTER

    def test_resolve_features_extra_enabled(self):
        result = resolve_features("starter", extra_enabled=["feat.advertising"])
        assert "feat.advertising" in result
        assert "feat.profit_tracking" in result

    def test_resolve_features_extra_disabled(self):
        result = resolve_features("standard", extra_disabled=["feat.alerts"])
        assert "feat.alerts" not in result
        assert "feat.profit_tracking" in result

    def test_resolve_features_all_tier(self):
        result = resolve_features("all")
        assert "feat.listing_crud" in result
        assert "feat.advertising" in result


# ── Feature Gate ─────────────────────────────────────────────────────────────

class TestFeatureGate:
    def test_gate_all_features_enabled(self):
        gate = FeatureGate(GLOBAL_SUITE)
        assert gate.is_enabled("feat.advertising") is True
        assert gate.is_enabled("feat.listing_crud") is True

    def test_gate_starter_blocks_advertising(self):
        gate = FeatureGate(STARTER)
        assert gate.is_enabled("feat.advertising") is False

    def test_check_raises_feature_disabled_error(self):
        gate = FeatureGate(STARTER)
        with pytest.raises(FeatureDisabledError) as exc_info:
            gate.check("feat.advertising", "test_tenant")
        assert exc_info.value.feature_id == "feat.advertising"

    def test_check_action_no_op_when_unmapped(self):
        gate = FeatureGate(frozenset())
        gate.check_action("system", "health", "t1")  # must not raise

    def test_check_action_raises_for_gated_action(self):
        gate = FeatureGate(STARTER)
        with pytest.raises(FeatureDisabledError):
            gate.check_action("ads", "campaign_list", "t1")

    def test_feature_disabled_error_to_dict(self):
        err = FeatureDisabledError("feat.advertising", "t1")
        d = err.to_dict()
        assert d["ok"] is False
        assert d["feature_disabled"] is True
        assert d["feature_id"] == "feat.advertising"
        assert "upgrade_hint" in d
        assert "required_tier" in d

    def test_gate_to_dict(self):
        gate = FeatureGate(STARTER)
        d = gate.to_dict()
        assert "enabled_count" in d
        assert "enabled" in d
        assert d["enabled_count"] == len(STARTER)


# ── Features domain via MCP tool ─────────────────────────────────────────────

class TestFeaturesDomainTool:
    def test_list_all_returns_ok(self):
        amazon_features = EXPORTS["amazon_features"]
        raw = _call(amazon_features("list_all"))
        assert raw["ok"] is True

    def test_list_all_has_features_array(self):
        amazon_features = EXPORTS["amazon_features"]
        raw = _call(amazon_features("list_all"))
        inner = _inner(raw)
        assert "features" in inner
        assert len(inner["features"]) == len(FEATURE_CATALOG)

    def test_list_all_feature_shape(self):
        amazon_features = EXPORTS["amazon_features"]
        raw = _call(amazon_features("list_all"))
        inner = _inner(raw)
        feat = inner["features"][0]
        assert "feature_id" in feat
        assert "display_name" in feat
        assert "tier_min" in feat
        assert "enabled" in feat

    def test_list_tiers_returns_all_tiers(self):
        amazon_features = EXPORTS["amazon_features"]
        raw = _call(amazon_features("list_tiers"))
        inner = _inner(raw)
        tier_names = {t["tier"] for t in inner.get("tiers", [])}
        assert {"starter", "standard", "advanced", "global_suite"}.issubset(tier_names)

    def test_get_tenant_config_ok(self):
        amazon_features = EXPORTS["amazon_features"]
        raw = _call(amazon_features("get_tenant_config"))
        inner = _inner(raw)
        assert inner["ok"] is True
        assert "enabled_count" in inner


# ── Feature gate in registry invoke() ────────────────────────────────────────

class TestRegistryGating:
    def test_gated_action_blocked_with_starter_gate(self):
        from amazon_mcp.tools.registry import invoke
        from amazon_mcp.features.feature_gate import get_gate
        gate = FeatureGate(STARTER)

        async def _run():
            with patch("amazon_mcp.features.feature_gate.get_gate", return_value=gate):
                return await invoke("ads", "campaign_list", {"tenant_id": "test_starter"})

        result = asyncio.run(_run())
        assert result.get("feature_disabled") is True
        assert result.get("ok") is False

    def test_system_domain_never_gated(self):
        from amazon_mcp.tools.registry import invoke
        gate = FeatureGate(frozenset())  # no features enabled

        async def _run():
            with patch("amazon_mcp.features.feature_gate.get_gate", return_value=gate):
                return await invoke("system", "health", {"tenant_id": "default"})

        result = asyncio.run(_run())
        assert result.get("ok") is True

    def test_features_domain_never_gated(self):
        from amazon_mcp.tools.registry import invoke
        gate = FeatureGate(frozenset())

        async def _run():
            with patch("amazon_mcp.features.feature_gate.get_gate", return_value=gate):
                return await invoke("features", "list_tiers", {"tenant_id": "default"})

        result = asyncio.run(_run())
        assert result.get("ok") is True

    def test_enabled_action_passes_gate(self):
        from amazon_mcp.tools.registry import invoke
        gate = FeatureGate(GLOBAL_SUITE)

        async def _run():
            with patch("amazon_mcp.features.feature_gate.get_gate", return_value=gate):
                return await invoke("inventory", "levels", {"tenant_id": "default"})

        result = asyncio.run(_run())
        assert result.get("feature_disabled") is not True


# ── Daily briefing feature gating ────────────────────────────────────────────

class TestDailyBriefingGating:
    def test_feat_enabled_none_means_all(self):
        from amazon_mcp.scenarios.daily_briefing import _feat_enabled
        assert _feat_enabled(None, "feat.advertising") is True
        assert _feat_enabled(None, "feat.profit_tracking") is True

    def test_feat_enabled_frozenset_gates(self):
        from amazon_mcp.scenarios.daily_briefing import _feat_enabled
        enabled = frozenset({"feat.profit_tracking"})
        assert _feat_enabled(enabled, "feat.profit_tracking") is True
        assert _feat_enabled(enabled, "feat.advertising") is False

    def test_feat_enabled_empty_blocks_all(self):
        from amazon_mcp.scenarios.daily_briefing import _feat_enabled
        assert _feat_enabled(frozenset(), "feat.profit_tracking") is False
