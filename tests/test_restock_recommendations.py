"""Tests for IPI score and restock_recommendations actions in inventory domain."""
from __future__ import annotations

import asyncio
import os
import pytest

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")

from amazon_mcp.clients.sp_api import SPAPIClient
from amazon_mcp.auth.lwa import LWAAuth
from amazon_mcp.clients.rate_limit import RateLimitRegistry
from amazon_mcp.config import AmazonConfig


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    import amazon_mcp.server as _srv
    _srv._reset_ctx_cache()


def _run(coro):
    return asyncio.run(coro)


def _make_client() -> SPAPIClient:
    cfg = AmazonConfig.from_env()
    auth = LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token)
    return SPAPIClient(cfg, auth, RateLimitRegistry())


# ── SpApi.get_restock_recommendations ────────────────────────────────────────

class TestSpApiRestockRecommendations:
    def _client(self):
        return _make_client()

    def test_returns_ok(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        assert result["ok"] is True

    def test_dry_run_flag(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        assert result["dry_run"] is True

    def test_has_recommendations_list(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        assert isinstance(result["recommendations"], list)

    def test_excludes_no_action_required(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        alert_types = {r["alert_type"] for r in result["recommendations"]}
        assert "No Action Required" not in alert_types

    def test_total_actionable_count(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        # fixture has 3 actionable rows (Reorder Now, Out of Stock, Low Inventory)
        assert result["total_actionable"] == 3

    def test_summary_keys(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        summary = result["summary"]
        assert "out_of_stock" in summary
        assert "reorder_now" in summary
        assert "low_inventory" in summary

    def test_out_of_stock_count(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        assert result["summary"]["out_of_stock"] == 1

    def test_reorder_now_count(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        assert result["summary"]["reorder_now"] == 1

    def test_low_inventory_count(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        assert result["summary"]["low_inventory"] == 1

    def test_recommendation_has_required_fields(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        rec = result["recommendations"][0]
        for field in ("asin", "sku", "alert_type", "available_qty", "days_of_supply"):
            assert field in rec, f"Missing field: {field}"

    def test_sorted_by_days_of_supply_ascending(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        recs = result["recommendations"]
        days = [r["days_of_supply"] for r in recs if r["days_of_supply"] is not None]
        assert days == sorted(days)

    def test_out_of_stock_first(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        recs = result["recommendations"]
        # Out of Stock has 0 days_of_supply → should be first
        assert recs[0]["alert_type"] == "Out of Stock"

    def test_recommended_qty_is_int_when_present(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        for rec in result["recommendations"]:
            qty = rec.get("recommended_replenishment_qty")
            if qty is not None:
                assert isinstance(qty, int)

    def test_sku_field_populated(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        for rec in result["recommendations"]:
            assert rec["sku"] != ""

    def test_asin_field_populated(self):
        client = self._client()
        result = _run(client.get_restock_recommendations())
        for rec in result["recommendations"]:
            assert rec["asin"] != ""


# ── SpApi.get_ipi_score ───────────────────────────────────────────────────────

class TestSpApiIpiScore:
    def _client(self):
        return _make_client()

    def test_returns_ok(self):
        client = self._client()
        result = _run(client.get_ipi_score())
        assert result["ok"] is True

    def test_dry_run_flag(self):
        client = self._client()
        result = _run(client.get_ipi_score())
        assert result["dry_run"] is True

    def test_ipi_score_is_int(self):
        client = self._client()
        result = _run(client.get_ipi_score())
        assert isinstance(result["ipi_score"], int)

    def test_ipi_score_matches_fixture(self):
        client = self._client()
        result = _run(client.get_ipi_score())
        # fixture has IPI = 380
        assert result["ipi_score"] == 380

    def test_ipi_label_present(self):
        client = self._client()
        result = _run(client.get_ipi_score())
        assert result["ipi_label"] in ("poor", "at_risk", "good", "excellent")

    def test_fixture_score_380_is_at_risk(self):
        client = self._client()
        result = _run(client.get_ipi_score())
        assert result["ipi_label"] == "at_risk"

    def test_threshold_warning_is_400(self):
        client = self._client()
        result = _run(client.get_ipi_score())
        assert result["threshold_warning"] == 400

    def test_sku_scores_list(self):
        client = self._client()
        result = _run(client.get_ipi_score())
        assert isinstance(result["sku_scores"], list)

    def test_sku_scores_have_required_fields(self):
        client = self._client()
        result = _run(client.get_ipi_score())
        for row in result["sku_scores"]:
            assert "sku" in row
            assert "ipi_score" in row
            assert "available" in row

    def test_note_field_present(self):
        client = self._client()
        result = _run(client.get_ipi_score())
        assert "note" in result
        assert "400" in result["note"]


# ── _REPORT_TYPES extension ───────────────────────────────────────────────────

class TestReportTypesRegistry:
    def test_restock_recommendations_in_registry(self):
        from amazon_mcp.clients.sp_api import _REPORT_TYPES
        assert "restock_recommendations" in _REPORT_TYPES

    def test_restock_recommendations_maps_to_correct_type(self):
        from amazon_mcp.clients.sp_api import _REPORT_TYPES
        assert _REPORT_TYPES["restock_recommendations"] == "GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT"

    def test_create_report_dry_run_restock(self):
        client = _make_client()
        result = _run(client.create_report("restock_recommendations"))
        assert result["ok"] is True
        assert result["reportId"] == "REPORT-DRY-RESTOCK"

    def test_get_report_status_dry_run_restock(self):
        client = _make_client()
        result = _run(client.get_report_status("REPORT-DRY-RESTOCK"))
        assert result["ok"] is True
        assert result["reportDocumentId"] == "DOC-DRY-RESTOCK"

    def test_download_report_document_dry_run_restock(self):
        client = _make_client()
        result = _run(client.download_report_document("DOC-DRY-RESTOCK"))
        assert result["ok"] is True
        assert result["report_type"] == "GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT"
        assert "preview" in result

    def test_restock_fixture_tsv_has_header(self):
        from pathlib import Path
        tsv = Path(__file__).parent / "fixtures" / "sp_api" / "restock_recommendations.tsv"
        assert tsv.exists()
        header = tsv.read_text().split("\n")[0]
        assert "alert-type" in header
        assert "recommended-replenishment-qty" in header


# ── inventory domain actions via domain handler ───────────────────────────────

class TestInventoryRestockAction:
    def _call_handler(self, action: str, **params):
        from amazon_mcp.tools.registry import DOMAIN_HANDLERS
        handler = DOMAIN_HANDLERS["inventory"][action]
        return _run(handler({"action": action, **params}))

    def test_restock_recommendations_handler_ok(self):
        result = self._call_handler("restock_recommendations")
        assert result["ok"] is True

    def test_restock_recommendations_has_recommendations(self):
        result = self._call_handler("restock_recommendations")
        assert "recommendations" in result
        assert isinstance(result["recommendations"], list)

    def test_ipi_score_handler_ok(self):
        result = self._call_handler("ipi_score")
        assert result["ok"] is True

    def test_ipi_score_handler_has_ipi_score(self):
        result = self._call_handler("ipi_score")
        assert "ipi_score" in result
        assert isinstance(result["ipi_score"], int)

    def test_restock_in_domain_handlers(self):
        from amazon_mcp.tools.registry import DOMAIN_HANDLERS
        assert "restock_recommendations" in DOMAIN_HANDLERS["inventory"]

    def test_ipi_score_in_domain_handlers(self):
        from amazon_mcp.tools.registry import DOMAIN_HANDLERS
        assert "ipi_score" in DOMAIN_HANDLERS["inventory"]


# ── feature_registry domain_actions ──────────────────────────────────────────

class TestInventoryFeatureRegistry:
    def _feat(self):
        from amazon_mcp.features.feature_registry import FEATURE_CATALOG
        return next(f for f in FEATURE_CATALOG if f.feature_id == "feat.inventory_management")

    def test_restock_recommendations_in_domain_actions(self):
        feat = self._feat()
        da = feat.domain_actions
        assert ("inventory", "restock_recommendations") in da

    def test_ipi_score_in_domain_actions(self):
        feat = self._feat()
        da = feat.domain_actions
        assert ("inventory", "ipi_score") in da
