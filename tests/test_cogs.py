"""COGS store and profit snapshot integration."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from amazon_mcp.cogs.store import CogsStore
from amazon_mcp.scenarios.profit_snapshot import build_profit_snapshot
from fixtures.fixture_sp_client import FixtureSPClient
from amazon_mcp.clients.ads_api import AdsAPIClient
from amazon_mcp.config import AmazonConfig
from amazon_mcp.auth.lwa import LWAAuth
from amazon_mcp.clients.rate_limit import RateLimitRegistry


@pytest.fixture
def dry_clients(monkeypatch, tmp_path):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    db = tmp_path / "cogs.db"
    monkeypatch.setenv("AMAZON_COGS_DB_PATH", str(db))
    cfg = AmazonConfig.from_env()
    auth = LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token)
    limits = RateLimitRegistry()
    sp = FixtureSPClient()
    ads = AdsAPIClient(cfg, auth, limits)
    store = CogsStore(db_path=str(db))
    return sp, ads, store


def test_import_csv_asin_cogs(tmp_path):
    store = CogsStore(db_path=str(tmp_path / "c.db"))
    result = store.import_csv("asin,cogs\nB0FIXTURE01,1200.0\nB0FIXTURE02,400.0\n")
    assert result["ok"] is True
    assert result["imported"] == 2
    assert store.get("B0FIXTURE01") == 1200.0


@pytest.mark.asyncio
async def test_profit_snapshot_uses_store_cogs(dry_clients):
    sp, ads, store = dry_clients
    store.import_csv("asin,cogs\nB0FIXTURE01,1500.0\nB0FIXTURE02,460.0\n")
    snap = await build_profit_snapshot(sp, ads, days=30, cogs_store=store)
    assert snap["data_completeness"]["cogs_source"] == "store"
    assert snap["data_completeness"]["margin_type"] == "store_cogs"
    assert snap["by_asin"]["B0FIXTURE01"]["cogs"] == 1500.0
    assert snap["by_asin"]["B0FIXTURE01"]["margin_status"] == "with_cogs"


@pytest.mark.asyncio
async def test_profit_snapshot_without_cogs_gap_transparent(dry_clients):
    sp, ads, store = dry_clients
    snap = await build_profit_snapshot(sp, ads, days=30, dry_run=False, cogs_store=store)
    assert snap["data_completeness"]["cogs_provided"] is False
    assert snap["by_asin"]["B0FIXTURE01"]["cogs"] is None
