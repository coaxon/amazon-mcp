"""Production-readiness regression tests covering audit findings."""
from __future__ import annotations

import asyncio
import os
import pytest

from amazon_mcp.config import AmazonConfig, _is_placeholder


# ── Config: placeholder detection ────────────────────────────────────────────

class TestPlaceholderDetection:
    def test_is_placeholder_matches_placeholder_prefix(self):
        assert _is_placeholder("PLACEHOLDER_LWA_CLIENT_ID")

    def test_is_placeholder_matches_xxxxx(self):
        assert _is_placeholder("Atzr|XXXXX_REFRESH")

    def test_is_placeholder_matches_your_(self):
        assert _is_placeholder("YOUR_SECRET_KEY")

    def test_is_placeholder_real_credential(self):
        assert not _is_placeholder("amzn1.application-oa2-client.abc123def456")

    def test_is_placeholder_real_token(self):
        assert not _is_placeholder("Atzr|IQEBLjAsABRabc123realtoken...")

    def test_has_placeholder_credentials_true(self, monkeypatch):
        monkeypatch.setenv("AMAZON_LWA_CLIENT_ID", "PLACEHOLDER_LWA")
        monkeypatch.setenv("AMAZON_LWA_CLIENT_SECRET", "secret")
        monkeypatch.setenv("AMAZON_LWA_REFRESH_TOKEN", "Atzr|real")
        monkeypatch.setenv("AMAZON_SELLER_ID", "A1REAL123")
        monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "0")
        cfg = AmazonConfig.from_env()
        assert cfg.has_placeholder_credentials is True

    def test_has_placeholder_credentials_false(self, monkeypatch):
        monkeypatch.setenv("AMAZON_LWA_CLIENT_ID", "amzn1.application-oa2-client.real123")
        monkeypatch.setenv("AMAZON_LWA_CLIENT_SECRET", "realsecret456")
        monkeypatch.setenv("AMAZON_LWA_REFRESH_TOKEN", "Atzr|realtoken789")
        monkeypatch.setenv("AMAZON_SELLER_ID", "A1SELLER456")
        monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "0")
        cfg = AmazonConfig.from_env()
        assert cfg.has_placeholder_credentials is False


class TestValidateLive:
    def test_validate_live_passes_in_dry_run(self, monkeypatch):
        monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
        cfg = AmazonConfig.from_env()
        assert cfg.validate_live() == []

    def test_validate_live_detects_missing(self, monkeypatch):
        monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "0")
        monkeypatch.setenv("AMAZON_LWA_CLIENT_ID", "")
        monkeypatch.setenv("AMAZON_LWA_CLIENT_SECRET", "")
        monkeypatch.setenv("AMAZON_LWA_REFRESH_TOKEN", "")
        monkeypatch.setenv("AMAZON_SELLER_ID", "")
        monkeypatch.setenv("AMAZON_MARKETPLACE_ID", "")
        cfg = AmazonConfig.from_env()
        missing = cfg.validate_live()
        assert "AMAZON_LWA_CLIENT_ID" in missing
        assert "AMAZON_SELLER_ID" in missing

    def test_validate_live_detects_placeholder_in_live_mode(self, monkeypatch):
        monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "0")
        monkeypatch.setenv("AMAZON_LWA_CLIENT_ID", "PLACEHOLDER_LWA")
        monkeypatch.setenv("AMAZON_LWA_CLIENT_SECRET", "real_secret")
        monkeypatch.setenv("AMAZON_LWA_REFRESH_TOKEN", "Atzr|real")
        monkeypatch.setenv("AMAZON_SELLER_ID", "A1REAL")
        monkeypatch.setenv("AMAZON_MARKETPLACE_ID", "ATVPDKIKX0DER")
        cfg = AmazonConfig.from_env()
        missing = cfg.validate_live()
        assert any("placeholder" in m.lower() for m in missing)

    def test_dry_run_defaults_to_true(self, monkeypatch):
        monkeypatch.delenv("AMAZON_MCP_DRY_RUN", raising=False)
        cfg = AmazonConfig.from_env()
        assert cfg.dry_run is True


# ── AlertEngine: dry_run loop suppression ─────────────────────────────────

class TestAlertEngineDryRun:
    def test_dry_run_inventory_loop_exits_immediately(self, tmp_path):
        from amazon_mcp.monitor.alert_store import AlertStore
        from amazon_mcp.monitor.alert_engine import AlertEngine
        store = AlertStore(db_path=str(tmp_path / "alerts.db"))
        engine = AlertEngine(store=store, sp_client=None, dry_run=True)

        ran = asyncio.run(engine._inventory_check_loop())
        # Should return without blocking (loop exits if dry_run)
        assert ran is None

    def test_dry_run_price_loop_exits_immediately(self, tmp_path):
        from amazon_mcp.monitor.alert_store import AlertStore
        from amazon_mcp.monitor.alert_engine import AlertEngine
        store = AlertStore(db_path=str(tmp_path / "alerts.db"))
        engine = AlertEngine(store=store, sp_client=None, dry_run=True)

        ran = asyncio.run(engine._price_check_loop())
        assert ran is None

    def test_consecutive_failure_counter_attribute_exists(self, tmp_path):
        from amazon_mcp.monitor.alert_store import AlertStore
        from amazon_mcp.monitor.alert_engine import AlertEngine
        store = AlertStore(db_path=str(tmp_path / "alerts.db"))
        engine = AlertEngine(store=store, sp_client=None, dry_run=False)
        # Streak counters exist and default to 0
        assert engine._inv_fail_streak == 0
        assert engine._price_fail_streak == 0
        assert engine._max_fail_streak == 5

    def test_check_inventory_succeeds_on_empty_store(self, tmp_path):
        from amazon_mcp.monitor.alert_store import AlertStore
        from amazon_mcp.monitor.alert_engine import AlertEngine
        store = AlertStore(db_path=str(tmp_path / "alerts.db"))
        engine = AlertEngine(store=store, sp_client=None, dry_run=False)
        result = asyncio.run(engine.check_inventory())
        assert result == 0  # no thresholds → no alerts, no exception


# ── AlertStore: tenant-aware DB path ─────────────────────────────────────

class TestAlertStoreTenantPath:
    def test_get_default_alert_db_path_default_tenant(self, monkeypatch):
        from amazon_mcp.monitor.alert_store import get_default_alert_db_path
        monkeypatch.delenv("AMAZON_SELLER_ID", raising=False)
        monkeypatch.delenv("AMAZON_MCP_ALERT_DB", raising=False)
        path = get_default_alert_db_path()
        assert path.endswith("alerts_default.db")

    def test_get_default_alert_db_path_placeholder(self, monkeypatch):
        from amazon_mcp.monitor.alert_store import get_default_alert_db_path
        monkeypatch.setenv("AMAZON_SELLER_ID", "PLACEHOLDER_SELLER_ID")
        monkeypatch.delenv("AMAZON_MCP_ALERT_DB", raising=False)
        path = get_default_alert_db_path()
        assert path.endswith("alerts_default.db")

    def test_get_default_alert_db_path_real_seller(self, monkeypatch):
        from amazon_mcp.monitor.alert_store import get_default_alert_db_path
        monkeypatch.setenv("AMAZON_SELLER_ID", "A1SELLER123")
        monkeypatch.delenv("AMAZON_MCP_ALERT_DB", raising=False)
        path = get_default_alert_db_path()
        assert path.endswith("alerts_A1SELLER123.db")

    def test_get_default_alert_db_path_override(self, monkeypatch, tmp_path):
        from amazon_mcp.monitor.alert_store import get_default_alert_db_path
        override = str(tmp_path / "custom.db")
        monkeypatch.setenv("AMAZON_MCP_ALERT_DB", override)
        path = get_default_alert_db_path()
        assert path == override
