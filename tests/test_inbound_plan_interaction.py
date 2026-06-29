"""Inbound plan Slack interaction flow — P1.6."""
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

from amazon_mcp.integrations.inbound_plan_interactions import (
    InboundPlanInteractionService,
    format_preview_blocks,
    mint_preview_token,
    verify_preview_token,
)
from amazon_mcp.integrations.slack_interactions import SlackInteractionHandler
from fixtures.fixture_sp_client import FixtureSPClient


@pytest.mark.asyncio
async def test_preview_flow_returns_confirm_buttons(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret")
    sp = FixtureSPClient()

    async def get_sp():
        return sp, True

    svc = InboundPlanInteractionService(get_sp_and_dry_run=get_sp)
    preview = await svc.preview(asin="B0FIXTURE01", quantity=100)
    blocks = format_preview_blocks(preview, "tester")
    action_ids = [el.get("action_id") for b in blocks if b.get("type") == "actions" for el in b.get("elements", [])]
    assert "confirm_inbound_plan" in action_ids
    assert "cancel_inbound_plan" in action_ids
    assert "LAX9" in blocks[0]["text"]["text"]


@pytest.mark.asyncio
async def test_confirm_calls_create_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(
        "amazon_mcp.integrations.inbound_plan_interactions._AUDIT_LOG",
        audit,
    )

    sp = FixtureSPClient()
    sp.create_inbound_plan = AsyncMock(return_value={
        "ok": True,
        "dry_run": True,
        "inboundPlanId": "FBA-PLAN-DRY-001",
        "operationId": "OP-DRY-001",
        "destinationFc": "LAX9",
    })

    async def get_sp():
        return sp, True

    svc = InboundPlanInteractionService(get_sp_and_dry_run=get_sp)
    token = mint_preview_token(asin="B0FIXTURE01", quantity=100, msku="SKU-FIX-001", destination_fc="LAX9")
    result = await svc.confirm(token=token, slack_user="ceo")
    assert result["ok"] is True
    assert result["dry_run"] is True
    sp.create_inbound_plan.assert_awaited_once()
    assert audit.exists()
    assert "inbound_plan_confirmed" in audit.read_text()


@pytest.mark.asyncio
async def test_cancel_no_write():
    handler = SlackInteractionHandler(
        dismiss_alert=lambda x: True,
        snooze_alert=lambda a, h: True,
        snooze_briefing_item=lambda k, h: True,
        acknowledge_briefing_item=lambda k: True,
    )
    create_called = {"v": False}

    async def fake_create(*a, **k):
        create_called["v"] = True

    payload = {
        "type": "block_actions",
        "user": {"username": "ceo"},
        "response_url": "https://hooks.example/resp",
        "message": {"blocks": []},
        "actions": [{
            "action_id": "cancel_inbound_plan",
            "block_id": "inbound_confirm_B0X",
            "value": json.dumps({"action_type": "cancel_inbound_plan", "asin": "B0X"}),
        }],
    }
    with patch("amazon_mcp.integrations.slack_interactions.post_response_url", new_callable=AsyncMock) as mock_post:
        await handler.handle_payload(payload)
    mock_post.assert_awaited_once()
    assert "Cancelled" in mock_post.await_args.args[1]["blocks"][0]["text"]["text"]
    assert create_called["v"] is False


@pytest.mark.asyncio
async def test_expired_token_rejected(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret")
    token = mint_preview_token(asin="B0FIXTURE01", quantity=50, msku="SKU-FIX-001", destination_fc="LAX9")
    token["exp"] = int(time.time()) - 10
    ok, err = verify_preview_token(token)
    assert not ok
    assert "expired" in err.lower()


@pytest.mark.asyncio
async def test_slack_confirm_interaction_message():
    monkeypatch_set = pytest.MonkeyPatch()
    monkeypatch_set.setenv("SLACK_SIGNING_SECRET", "test_secret")

    sp = FixtureSPClient()
    sp.create_inbound_plan = AsyncMock(return_value={
        "ok": True,
        "dry_run": True,
        "inboundPlanId": "FBA-PLAN-DRY-001",
    })

    async def get_sp():
        return sp, True

    svc = InboundPlanInteractionService(get_sp_and_dry_run=get_sp)
    handler = SlackInteractionHandler(
        dismiss_alert=lambda x: True,
        snooze_alert=lambda a, h: True,
        snooze_briefing_item=lambda k, h: True,
        acknowledge_briefing_item=lambda k: True,
        inbound_plan_service=svc,
    )
    token = mint_preview_token(asin="B0FIXTURE01", quantity=80, msku="SKU-FIX-001", destination_fc="LAX9")
    value = json.dumps({"action_type": "confirm_inbound_plan", **token})
    payload = {
        "type": "block_actions",
        "user": {"username": "ceo"},
        "response_url": "https://hooks.example/resp",
        "message": {"blocks": []},
        "actions": [{"action_id": "confirm_inbound_plan", "block_id": "inbound_confirm_B0FIXTURE01", "value": value}],
    }
    with patch("amazon_mcp.integrations.slack_interactions.post_response_url", new_callable=AsyncMock) as mock_post:
        await handler.handle_payload(payload)
    text = mock_post.await_args.args[1]["blocks"][0]["text"]["text"]
    assert "Inbound plan created" in text
    assert "DEMO MODE" in text
    monkeypatch_set.undo()


def _make_svc():
    async def _get_sp():
        return FixtureSPClient(), True
    return InboundPlanInteractionService(get_sp_and_dry_run=_get_sp)


@pytest.mark.asyncio
async def test_preview_quantity_zero_raises():
    with pytest.raises(ValueError, match="positive"):
        await _make_svc().preview(asin="B0FIXTURE01", quantity=0)


@pytest.mark.asyncio
async def test_preview_quantity_negative_raises():
    with pytest.raises(ValueError, match="positive"):
        await _make_svc().preview(asin="B0FIXTURE01", quantity=-1)


@pytest.mark.asyncio
async def test_preview_quantity_too_large_raises():
    with pytest.raises(ValueError, match="10,000"):
        await _make_svc().preview(asin="B0FIXTURE01", quantity=10_001)


@pytest.mark.asyncio
async def test_confirm_denied_unauthorized_slack_user(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret")
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps({
        "mappings": [{
            "slack_user_id": "U_CEO",
            "tenant_id": "default",
            "allowed_actions": ["confirm_inbound_plan"],
        }],
    }))
    monkeypatch.setenv("AMAZON_SLACK_PERMISSIONS_PATH", str(perms))
    from amazon_mcp.gateway import slack_permissions as spm
    spm._store_cache.clear()

    sp = FixtureSPClient()
    sp.create_inbound_plan = AsyncMock(return_value={"ok": True, "inboundPlanId": "X"})

    async def get_sp():
        return sp, True

    svc = InboundPlanInteractionService(get_sp_and_dry_run=get_sp)
    token = mint_preview_token(asin="B0FIXTURE01", quantity=10, msku="SKU-FIX-001", destination_fc="LAX9")
    result = await svc.confirm(token=token, slack_user="intruder", slack_user_id="U_INTRUDER")
    assert result["ok"] is False
    assert "not authorized" in result["error"].lower()
    sp.create_inbound_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_slack_confirm_denied_unmapped_user(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret")
    perms = tmp_path / "perms.json"
    perms.write_text(json.dumps({
        "mappings": [{"slack_user_id": "U_CEO", "tenant_id": "default", "allowed_actions": ["*"]}],
    }))
    monkeypatch.setenv("AMAZON_SLACK_PERMISSIONS_PATH", str(perms))
    from amazon_mcp.gateway import slack_permissions as spm
    spm._store_cache.clear()

    svc = InboundPlanInteractionService(get_sp_and_dry_run=lambda: (_ for _ in ()).throw(StopIteration))
    async def get_sp():
        sp = FixtureSPClient()
        sp.create_inbound_plan = AsyncMock(return_value={"ok": True, "inboundPlanId": "X"})
        return sp, True
    svc = InboundPlanInteractionService(get_sp_and_dry_run=get_sp)
    handler = SlackInteractionHandler(
        dismiss_alert=lambda x: True,
        snooze_alert=lambda a, h: True,
        snooze_briefing_item=lambda k, h: True,
        acknowledge_briefing_item=lambda k: True,
        inbound_plan_service=svc,
    )
    token = mint_preview_token(asin="B0FIXTURE01", quantity=10, msku="SKU-FIX-001", destination_fc="LAX9")
    value = json.dumps({"action_type": "confirm_inbound_plan", **token})
    payload = {
        "type": "block_actions",
        "user": {"id": "U_INTRUDER", "username": "intruder"},
        "response_url": "https://hooks.example/resp",
        "message": {"blocks": []},
        "actions": [{"action_id": "confirm_inbound_plan", "value": value}],
    }
    with patch("amazon_mcp.integrations.slack_interactions.post_response_url", new_callable=AsyncMock) as mock_post:
        await handler.handle_payload(payload)
    text = mock_post.await_args.args[1]["blocks"][0]["text"]["text"]
    assert "not authorized" in text.lower() or "🚫" in text
