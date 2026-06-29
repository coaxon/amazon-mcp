"""Input validation guards added in D-series audit — all negative-path assertions."""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")

from amazon_mcp.server import (
    add_price_watch,
    competitor_price_alert,
    get_fee_estimate,
    get_profit_analysis,
    protect_profit_margin,
)


def _err(raw: str) -> str:
    d = json.loads(raw)
    assert d["ok"] is False, f"Expected ok=False, got {d}"
    return d.get("error", "")


@pytest.mark.asyncio
async def test_fee_estimate_negative_price():
    assert "must be greater than 0" in _err(await get_fee_estimate("B0POC00001", -5.0))


@pytest.mark.asyncio
async def test_fee_estimate_zero_price():
    assert "must be greater than 0" in _err(await get_fee_estimate("B0POC00001", 0.0))


@pytest.mark.asyncio
async def test_fee_estimate_implausibly_large_price():
    assert "implausibly large" in _err(await get_fee_estimate("B0POC00001", 200_001.0))


@pytest.mark.asyncio
async def test_fee_estimate_empty_asin():
    assert "asin" in _err(await get_fee_estimate("", 29.99)).lower()


@pytest.mark.asyncio
async def test_fee_estimate_short_asin():
    assert "asin" in _err(await get_fee_estimate("B", 29.99)).lower()


@pytest.mark.asyncio
async def test_profit_analysis_negative_cogs():
    assert "cogs" in _err(await get_profit_analysis("B0POC00001", 29.99, cogs=-1.0)).lower()


@pytest.mark.asyncio
async def test_profit_analysis_days_too_large():
    assert "days" in _err(await get_profit_analysis("B0POC00001", 29.99, days=366)).lower()


@pytest.mark.asyncio
async def test_profit_analysis_days_zero():
    assert "days" in _err(await get_profit_analysis("B0POC00001", 29.99, days=0)).lower()


@pytest.mark.asyncio
async def test_protect_profit_margin_margin_at_one():
    assert "target_margin" in _err(await protect_profit_margin("B0POC00001", 1.0)).lower()


@pytest.mark.asyncio
async def test_protect_profit_margin_negative_margin():
    assert "target_margin" in _err(await protect_profit_margin("B0POC00001", -0.1)).lower()


@pytest.mark.asyncio
async def test_price_watch_invalid_direction():
    err = _err(await add_price_watch("B0POC00001", 29.99, 0.05, "sideways"))
    assert "direction" in err.lower()


@pytest.mark.asyncio
async def test_price_watch_zero_baseline():
    err = _err(await add_price_watch("B0POC00001", 0.0, 0.05, "any"))
    assert "baseline_price" in err.lower() or "greater than 0" in err.lower()


@pytest.mark.asyncio
async def test_competitor_price_alert_valid():
    raw = await competitor_price_alert("B0POC00001", 0.05)
    d = json.loads(raw)
    assert d["ok"] is True


@pytest.mark.asyncio
async def test_profit_analysis_zero_cogs_computes_margin():
    """cogs=0.0 must not be treated as 'not provided' — margin should be computed."""
    raw = await get_profit_analysis("B0POC00001", 29.99, cogs=0.0, days=30)
    d = json.loads(raw)
    assert d["ok"] is True
    assert d["cogs"] == 0.0, "cogs field must echo 0.0, not 'not_provided'"
    assert d["gross_margin_usd"] is not None, "margin must be computed when cogs=0"
    assert d["gross_margin_pct"] is not None
    assert d["gross_margin_usd"] > 0, "margin > 0 when cogs=0 and price covers fees"


@pytest.mark.asyncio
async def test_profit_analysis_high_cogs_negative_margin():
    """cogs >= price means negative margin — must be returned, not errored."""
    raw = await get_profit_analysis("B0POC00001", 5.00, cogs=20.00, days=30)
    d = json.loads(raw)
    assert d["ok"] is True
    assert d["gross_margin_usd"] < 0
    assert d["gross_margin_pct"] < 0


def test_notifier_config_webhook_url_must_be_https():
    # http:// scheme is rejected
    import pytest as _pt
    from amazon_mcp.monitor.notifier import NotifierConfig
    with _pt.raises(ValueError, match="https://"):
        NotifierConfig(slack_webhook_url="http://hooks.slack.com/x")


def test_notifier_config_discord_url_must_be_https():
    import pytest as _pt
    from amazon_mcp.monitor.notifier import NotifierConfig
    with _pt.raises(ValueError, match="https://"):
        NotifierConfig(discord_webhook_url="http://discord.com/api/webhooks/x")


def test_notifier_config_empty_urls_ok():
    # Empty strings should not raise
    from amazon_mcp.monitor.notifier import NotifierConfig
    cfg = NotifierConfig()
    assert cfg.slack_webhook_url == ""
    assert cfg.discord_webhook_url == ""
    assert cfg.webhook_url == ""
