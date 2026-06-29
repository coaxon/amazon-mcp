"""Tests for Cross-Tenant Benchmark domain."""
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

from amazon_mcp.tools.benchmark import (
    _percentile_rank,
    _percentile_label,
    _improvement_hint,
    get_percentile,
    acos_benchmark,
    margin_benchmark,
    full_benchmark_report,
    category_comparison,
)
from amazon_mcp.tools.registry import dispatch_domain


@pytest.fixture(autouse=True)
def _ensure_registry():
    import amazon_mcp.server  # noqa: F401
    yield


# ── _percentile_rank unit ─────────────────────────────────────────────────────

class TestPercentileRank:
    def test_below_all(self):
        assert _percentile_rank(0.0, [10, 20, 30]) == 0

    def test_above_all(self):
        assert _percentile_rank(100.0, [10, 20, 30]) == 100

    def test_middle(self):
        dist = [10.0, 20.0, 30.0, 40.0, 50.0]
        # value=25 → 2 values below (10, 20) → 2/5 = 40
        assert _percentile_rank(25.0, dist) == 40

    def test_exact_match_counts_as_not_below(self):
        dist = [10.0, 20.0, 30.0]
        # value=20 → 1 value below (10) → 1/3 = 33
        assert _percentile_rank(20.0, dist) == 33

    def test_empty_distribution_returns_50(self):
        assert _percentile_rank(99.0, []) == 50


# ── _percentile_label unit ────────────────────────────────────────────────────

class TestPercentileLabel:
    def test_top_20(self):
        assert "top 20%" in _percentile_label(85)

    def test_above_average(self):
        assert "above average" in _percentile_label(65)

    def test_average(self):
        assert "average" in _percentile_label(45)

    def test_below_average(self):
        assert "below average" in _percentile_label(25)

    def test_bottom_20(self):
        assert "bottom 20%" in _percentile_label(10)


# ── get_percentile ────────────────────────────────────────────────────────────

class TestGetPercentile:
    @pytest.mark.asyncio
    async def test_single_known_metric(self):
        result = await get_percentile({"metrics": {"acos_pct": 20.0}})
        assert result["ok"] is True
        acos = result["results"]["acos_pct"]
        assert "percentile" in acos
        assert "label" in acos
        assert acos["value"] == 20.0

    @pytest.mark.asyncio
    async def test_multiple_metrics(self):
        result = await get_percentile({"metrics": {"acos_pct": 15.0, "net_margin_pct": 18.0}})
        assert result["ok"] is True
        assert "acos_pct" in result["results"]
        assert "net_margin_pct" in result["results"]

    @pytest.mark.asyncio
    async def test_unknown_metric_error(self):
        result = await get_percentile({"metrics": {"fake_metric": 50.0}})
        assert result["ok"] is True  # overall ok, but individual metric has error
        assert result["results"]["fake_metric"]["ok"] is False

    @pytest.mark.asyncio
    async def test_empty_metrics_returns_error(self):
        result = await get_percentile({})
        assert result["ok"] is False
        assert "supported_metrics" in result

    @pytest.mark.asyncio
    async def test_convenience_params(self):
        result = await get_percentile({"acos_pct": 24.5})
        assert result["ok"] is True
        assert "acos_pct" in result["results"]

    @pytest.mark.asyncio
    async def test_privacy_note_present(self):
        result = await get_percentile({"metrics": {"acos_pct": 20.0}})
        assert "privacy_note" in result

    @pytest.mark.asyncio
    async def test_dry_run_flagged(self):
        result = await get_percentile({"metrics": {"acos_pct": 20.0}})
        assert result["dry_run"] is True


# ── acos_benchmark / margin_benchmark ─────────────────────────────────────────

class TestQuickBenchmarks:
    @pytest.mark.asyncio
    async def test_acos_benchmark_ok(self):
        result = await acos_benchmark({"acos_pct": 22.0})
        assert result["ok"] is True
        assert "acos_pct" in result["results"]

    @pytest.mark.asyncio
    async def test_acos_benchmark_missing_param(self):
        result = await acos_benchmark({})
        assert result["ok"] is False
        assert "acos_pct" in result["error"]

    @pytest.mark.asyncio
    async def test_margin_benchmark_ok(self):
        result = await margin_benchmark({"net_margin_pct": 14.0})
        assert result["ok"] is True
        assert "net_margin_pct" in result["results"]

    @pytest.mark.asyncio
    async def test_margin_benchmark_missing_param(self):
        result = await margin_benchmark({})
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_low_acos_is_low_percentile_rank(self):
        # ACOS lower=better: 9% ACOS → few sellers below → low rank, but excellent performance
        result = await acos_benchmark({"acos_pct": 9.0})
        pct = result["results"]["acos_pct"]["percentile"]
        assert pct <= 20  # only the 8.5 entry is below 9 in dry distribution

    @pytest.mark.asyncio
    async def test_high_acos_is_high_percentile_rank(self):
        # 50% ACOS → most sellers are below → high rank (meaning most outperform you)
        result = await acos_benchmark({"acos_pct": 50.0})
        pct = result["results"]["acos_pct"]["percentile"]
        assert pct >= 80

    @pytest.mark.asyncio
    async def test_high_margin_is_high_percentile(self):
        # net_margin higher=better: 35% → most sellers below → high rank = good
        result = await margin_benchmark({"net_margin_pct": 35.0})
        pct = result["results"]["net_margin_pct"]["percentile"]
        assert pct >= 70


# ── full_benchmark_report ─────────────────────────────────────────────────────

class TestFullBenchmarkReport:
    @pytest.mark.asyncio
    async def test_all_metrics_at_median(self):
        result = await full_benchmark_report({
            "metrics": {
                "acos_pct": 21.0,
                "net_margin_pct": 18.0,
                "return_rate_pct": 7.0,
            }
        })
        assert result["ok"] is True
        assert "opportunities" in result
        assert "summary" in result

    @pytest.mark.asyncio
    async def test_poor_metrics_generate_opportunities(self):
        result = await full_benchmark_report({
            "metrics": {
                "acos_pct": 55.0,        # very high ACOS → bottom 10%
                "net_margin_pct": 2.0,   # very low margin → bottom 10%
            }
        })
        assert result["ok"] is True
        assert len(result["opportunities"]) >= 1
        opp_metrics = [o["metric"] for o in result["opportunities"]]
        assert "acos_pct" in opp_metrics or "net_margin_pct" in opp_metrics

    @pytest.mark.asyncio
    async def test_opportunity_has_suggestion(self):
        result = await full_benchmark_report({"metrics": {"acos_pct": 60.0}})
        if result["opportunities"]:
            assert "suggestion" in result["opportunities"][0]

    @pytest.mark.asyncio
    async def test_opportunities_sorted_by_percentile(self):
        result = await full_benchmark_report({
            "metrics": {
                "acos_pct": 55.0,
                "net_margin_pct": 2.0,
                "return_rate_pct": 0.5,  # good
            }
        })
        pcts = [o["percentile"] for o in result.get("opportunities", [])]
        assert pcts == sorted(pcts)

    @pytest.mark.asyncio
    async def test_empty_metrics_returns_error(self):
        result = await full_benchmark_report({})
        assert result["ok"] is False


# ── category_comparison ────────────────────────────────────────────────────────

class TestCategoryComparison:
    @pytest.mark.asyncio
    async def test_general_category(self):
        result = await category_comparison({"category": "general"})
        assert result["ok"] is True
        assert result["category"] == "general"
        assert "acos_pct" in result["benchmarks"]

    @pytest.mark.asyncio
    async def test_electronics_category(self):
        result = await category_comparison({"category": "electronics"})
        assert result["ok"] is True
        # Electronics has higher return rates
        elec_return = result["benchmarks"]["return_rate_pct"]["category_median"]
        gen_result = await category_comparison({"category": "general"})
        gen_return = gen_result["benchmarks"]["return_rate_pct"]["category_median"]
        assert elec_return >= gen_return

    @pytest.mark.asyncio
    async def test_unknown_category_defaults_to_general(self):
        result = await category_comparison({"category": "mystery_category"})
        assert result["ok"] is True
        assert result["benchmarks"]["acos_pct"]["adjustment_factor"] == 1.0

    @pytest.mark.asyncio
    async def test_all_metrics_in_response(self):
        result = await category_comparison({})
        for metric in ("acos_pct", "net_margin_pct", "return_rate_pct",
                       "inventory_health", "account_health", "reorder_fill_rate"):
            assert metric in result["benchmarks"]


# ── _improvement_hint ─────────────────────────────────────────────────────────

class TestImprovementHints:
    def test_known_metric_has_hint(self):
        for m in ("acos_pct", "net_margin_pct", "return_rate_pct",
                  "inventory_health", "account_health", "reorder_fill_rate"):
            hint = _improvement_hint(m)
            assert len(hint) > 10

    def test_unknown_metric_has_generic_hint(self):
        hint = _improvement_hint("nonexistent_metric")
        assert "daily briefing" in hint


# ── Domain tool via dispatch_domain ───────────────────────────────────────────

class TestBenchmarkDomainTool:
    @pytest.mark.asyncio
    async def test_get_percentile(self):
        raw = await dispatch_domain("benchmark", "get_percentile",
                                    {"metrics": {"acos_pct": 22.0}})
        data = json.loads(raw)
        assert data["ok"] is True
        assert "acos_pct" in data["data"]["results"]

    @pytest.mark.asyncio
    async def test_acos_benchmark(self):
        raw = await dispatch_domain("benchmark", "acos_benchmark", {"acos_pct": 18.0})
        data = json.loads(raw)
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_margin_benchmark(self):
        raw = await dispatch_domain("benchmark", "margin_benchmark", {"net_margin_pct": 20.0})
        data = json.loads(raw)
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_full_benchmark_report(self):
        raw = await dispatch_domain("benchmark", "full_benchmark_report",
                                    {"metrics": {"acos_pct": 30.0, "net_margin_pct": 5.0}})
        data = json.loads(raw)
        assert data["ok"] is True
        assert "opportunities" in data["data"]

    @pytest.mark.asyncio
    async def test_category_comparison(self):
        raw = await dispatch_domain("benchmark", "category_comparison",
                                    {"category": "apparel"})
        data = json.loads(raw)
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        raw = await dispatch_domain("benchmark", "no_such_action", {})
        data = json.loads(raw)
        assert data["ok"] is False


# ── Feature gate: benchmark requires standard tier ────────────────────────────

class TestBenchmarkFeatureGate:
    @pytest.mark.asyncio
    async def test_starter_tenant_blocked(self):
        from amazon_mcp.features.feature_gate import set_tenant_tier
        set_tenant_tier("test_starter_bench", "starter")
        raw = await dispatch_domain("benchmark", "acos_benchmark",
                                    {"tenant_id": "test_starter_bench", "acos_pct": 20.0})
        data = json.loads(raw)
        assert data.get("ok") is False or data.get("data", {}).get("feature_disabled") is True

    @pytest.mark.asyncio
    async def test_standard_tenant_allowed(self):
        from amazon_mcp.features.feature_gate import set_tenant_tier
        set_tenant_tier("test_std_bench", "standard")
        raw = await dispatch_domain("benchmark", "acos_benchmark",
                                    {"tenant_id": "test_std_bench", "acos_pct": 20.0})
        data = json.loads(raw)
        assert data["ok"] is True
