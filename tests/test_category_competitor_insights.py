"""category_competitor_insights with fixture-driven browse tree."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.tools.domain_tools import EXPORTS
import amazon_mcp.server as srv


@pytest.mark.asyncio
async def test_category_competitor_insights_fixture_dry_run(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    srv._reset_ctx_cache()
    amazon_catalog = EXPORTS["amazon_catalog"]
    raw = await amazon_catalog(action="competitor_insights", asin="B0FIXTURE01")
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    data = envelope.get("data", envelope)
    assert data["category_browse_tree"]["depth"] == 3
    assert data["category_browse_tree"]["path_names"][0] == "Electronics"
    assert data["product"]["leaf_classification_id"] == "7073956011"
    assert data["competition"]["total_offers"] == 3
    assert data["pricing"]["buy_box_price"] == 28.99
    assert "stub" not in raw.lower()
