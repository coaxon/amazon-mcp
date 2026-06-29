"""Pause Ad Slack interaction flow — P1.5 B15."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from amazon_mcp.integrations.pause_ad_interactions import (
    PauseAdInteractionService,
    format_pause_ad_preview_blocks,
    mint_pause_ad_preview_token,
    verify_pause_ad_preview_token,
)
from amazon_mcp.integrations.slack_interactions import SlackInteractionHandler
from amazon_mcp.integrations.slack_blocks import _build_pause_ad_action_blocks


class _DryAds:
    async def list_campaigns(self, state_filter: str = "enabled"):
        return {
            "ok": True,
            "campaigns": [
                {"campaignId": "C001", "name": "SP-Auto-Main", "state": "enabled"},
                {"campaignId": "C002", "name": "SP-Manual-KW", "state": "enabled"},
            ],
        }

    async def pause_campaign(self, campaign_id: str):
        return {
            "ok": True,
            "dry_run": True,
            "campaignId": campaign_id,
            "action": "PAUSED",
            "previous_state": "enabled",
            "new_state": "paused",
        }


def _handler(svc: PauseAdInteractionService) -> SlackInteractionHandler:
    return SlackInteractionHandler(
        dismiss_alert=lambda x: True,
        snooze_alert=lambda a, h: True,
        snooze_briefing_item=lambda k, h: True,
        acknowledge_briefing_item=lambda k: True,
        pause_ad_service=svc,
    )


@pytest.mark.asyncio
async def test_preview_lists_campaigns_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret")
    preview_audit = tmp_path / "preview.jsonl"
    monkeypatch.setattr("amazon_mcp.integrations.pause_ad_interactions._PREVIEW_AUDIT", preview_audit)
    ads = _DryAds()

    async def get_ads():
        return ads, True

    svc = PauseAdInteractionService(get_ads_and_dry_run=get_ads)
    preview = await svc.preview(
        rule_id="pause_ads_low_cover",
        reason="Inventory cover 0.7d < 7.0d threshold AND ACoS 22.0% < 25%",
    )
    assert len(preview.campaigns) == 2
    blocks = format_pause_ad_preview_blocks(preview, "ceo")
    ids = [el.get("action_id") for b in blocks if b.get("type") == "actions" for el in b.get("elements", [])]
    assert "confirm_pause_campaign" in ids
    assert preview_audit.exists()
    assert "pause_ad_preview" in preview_audit.read_text()


@pytest.mark.asyncio
async def test_confirm_pauses_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret")
    confirm_audit = tmp_path / "confirm.jsonl"
    monkeypatch.setattr("amazon_mcp.integrations.pause_ad_interactions._CONFIRM_AUDIT", confirm_audit)
    ads = _DryAds()
    ads.pause_campaign = AsyncMock(side_effect=ads.pause_campaign)

    async def get_ads():
        return ads, True

    svc = PauseAdInteractionService(get_ads_and_dry_run=get_ads)
    token = mint_pause_ad_preview_token(
        rule_id="pause_ads_low_cover",
        reason="test reason",
        campaign_ids=["C001", "C002"],
        campaigns=[{"campaign_id": "C001", "name": "A", "state": "enabled"}],
    )
    result = await svc.confirm(token=token, slack_user="ceo", slack_user_id="U_CEO")
    assert result["ok"] is True
    assert result["paused_count"] == 2
    assert ads.pause_campaign.await_count == 2
    lines = confirm_audit.read_text().strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["rule_id"] == "pause_ads_low_cover"
    assert rec["action"] == "PAUSED"
    assert rec["dry_run"] is True


@pytest.mark.asyncio
async def test_confirm_denied_unauthorized(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret")
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps({
        "mappings": [{"slack_user_id": "U_CEO", "tenant_id": "default", "allowed_actions": ["confirm_pause_campaign"]}],
    }))
    monkeypatch.setenv("AMAZON_SLACK_PERMISSIONS_PATH", str(perms))
    from amazon_mcp.gateway import slack_permissions as spm
    spm._store_cache.clear()

    ads = _DryAds()
    ads.pause_campaign = AsyncMock()

    async def get_ads():
        return ads, True

    svc = PauseAdInteractionService(get_ads_and_dry_run=get_ads)
    token = mint_pause_ad_preview_token(
        rule_id="pause_ads_low_cover", reason="r", campaign_ids=["C001"], campaigns=[],
    )
    result = await svc.confirm(token=token, slack_user="x", slack_user_id="U_INTRUDER")
    assert result["ok"] is False
    assert "not authorized" in result["error"].lower()
    ads.pause_campaign.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_token_rejected(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret")
    token = mint_pause_ad_preview_token(
        rule_id="pause_ads_low_cover", reason="r", campaign_ids=["C001"], campaigns=[],
    )
    token["exp"] = int(time.time()) - 5
    ok, err = verify_pause_ad_preview_token(token)
    assert not ok
    assert "expired" in err.lower()


def test_slack_blocks_preview_pause_button():
    briefing = {
        "recommended_actions": [{
            "rule_id": "pause_ads_low_cover",
            "urgency": "HIGH",
            "action": "Pause or reduce ad spend",
            "reason": "Inventory cover 0.7d < 7.0d threshold",
            "source": "cross_domain_rule",
        }],
    }
    blocks = _build_pause_ad_action_blocks(briefing)
    assert blocks
    elements = [el for b in blocks if b.get("type") == "actions" for el in b["elements"]]
    btn = next(el for el in elements if el["action_id"] == "preview_pause_campaign")
    assert all(el["action_id"] != "toggle_rationale" for el in elements)
    meta = json.loads(btn["value"])
    assert meta["rule_id"] == "pause_ads_low_cover"


@pytest.mark.asyncio
async def test_slack_confirm_interaction_message(monkeypatch, tmp_path):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret")
    monkeypatch.setattr("amazon_mcp.integrations.pause_ad_interactions._CONFIRM_AUDIT", tmp_path / "a.jsonl")
    ads = _DryAds()
    ads.pause_campaign = AsyncMock(side_effect=ads.pause_campaign)

    async def get_ads():
        return ads, True

    svc = PauseAdInteractionService(get_ads_and_dry_run=get_ads)
    handler = _handler(svc)
    token = mint_pause_ad_preview_token(
        rule_id="pause_ads_low_cover",
        reason="Inventory cover low",
        campaign_ids=["C001"],
        campaigns=[{"campaign_id": "C001", "name": "SP-Auto", "state": "enabled"}],
    )
    value = json.dumps({"action_type": "confirm_pause_campaign", **token})
    payload = {
        "type": "block_actions",
        "user": {"id": "U_CEO", "username": "ceo"},
        "response_url": "https://hooks.example/resp",
        "message": {"blocks": []},
        "actions": [{"action_id": "confirm_pause_campaign", "block_id": "pause_ad_confirm_x", "value": value}],
    }
    with patch("amazon_mcp.integrations.slack_interactions.post_response_url", new_callable=AsyncMock) as mock_post:
        await handler.handle_payload(payload)
    text = mock_post.await_args.args[1]["blocks"][0]["text"]["text"]
    assert "Paused" in text
    assert "DEMO MODE" in text


@pytest.mark.asyncio
async def test_ads_pause_campaign_dry_run(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DRY_RUN", "1")
    from amazon_mcp.auth.lwa import LWAAuth
    from amazon_mcp.clients.ads_api import AdsAPIClient
    from amazon_mcp.clients.rate_limit import RateLimitRegistry
    from amazon_mcp.config import AmazonConfig

    cfg = AmazonConfig.from_env()
    auth = LWAAuth(cfg.lwa_client_id, cfg.lwa_client_secret, cfg.lwa_refresh_token)
    ads = AdsAPIClient(cfg, auth, RateLimitRegistry())
    result = await ads.pause_campaign("C001")
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["action"] == "PAUSED"
