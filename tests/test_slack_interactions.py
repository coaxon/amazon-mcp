"""Slack interactive components — signature, acknowledge, snooze."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import pytest
from starlette.testclient import TestClient

from amazon_mcp.integrations.slack_interactions import (
    SlackInteractionHandler,
    create_slack_interactions_route,
    parse_interaction_payload,
    verify_slack_signature,
)
from amazon_mcp.monitor.alert_engine import AlertEngine
from amazon_mcp.monitor.alert_store import AlertStore
from amazon_mcp.monitor.thresholds import AlertRecord, InventoryThreshold


def _sign(body: bytes, secret: str, ts: str | None = None) -> tuple[str, str]:
    ts = ts or str(int(time.time()))
    basestring = f"v0:{ts}:{body.decode()}"
    sig = "v0=" + hmac.new(secret.encode(), basestring.encode(), hashlib.sha256).hexdigest()
    return ts, sig


def _payload_body(payload: dict) -> bytes:
    return urlencode({"payload": json.dumps(payload)}).encode()


def test_verify_slack_signature_valid():
    secret = "test_secret"
    body = b"payload=%7B%7D"
    ts, sig = _sign(body, secret)
    assert verify_slack_signature(signing_secret=secret, body=body, timestamp=ts, signature=sig)


def test_verify_slack_signature_rejects_bad_sig():
    body = b"payload=x"
    ts = str(int(time.time()))
    assert not verify_slack_signature(
        signing_secret="secret",
        body=body,
        timestamp=ts,
        signature="v0=deadbeef",
    )


def test_parse_interaction_payload():
    inner = {"type": "block_actions", "actions": []}
    body = _payload_body(inner)
    parsed = parse_interaction_payload(body)
    assert parsed["type"] == "block_actions"


@pytest.mark.asyncio
async def test_acknowledge_dismisses_alert_and_updates_response_url():
    dismissed: list[str] = []

    handler = SlackInteractionHandler(
        dismiss_alert=lambda aid: dismissed.append(aid) or True,
        snooze_alert=lambda aid, h: False,
        snooze_briefing_item=lambda k, h: False,
        acknowledge_briefing_item=lambda k: False,
    )

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "alert"}},
        {
            "type": "actions",
            "block_id": "actions_inventory_alert_abc",
            "elements": [],
        },
    ]
    payload = {
        "type": "block_actions",
        "user": {"username": "ceo"},
        "response_url": "https://hooks.slack.com/response/test",
        "message": {"blocks": blocks},
        "actions": [{
            "action_id": "acknowledge",
            "block_id": "actions_inventory_alert_abc",
            "value": json.dumps({
                "action_type": "acknowledge",
                "item_kind": "inventory_alert",
                "alert_id": "abc123",
                "asin": "B0TEST",
            }),
        }],
    }

    with patch("amazon_mcp.integrations.slack_interactions.post_response_url", new_callable=AsyncMock) as mock_post:
        await handler.handle_payload(payload)

    assert dismissed == ["abc123"]
    mock_post.assert_awaited_once()
    sent = mock_post.await_args.args[1]
    assert "Acknowledged" in sent["blocks"][-1]["elements"][0]["text"]
    assert not any(b.get("type") == "actions" for b in sent["blocks"])


@pytest.mark.asyncio
async def test_snooze_blocks_alert_engine_reemit(tmp_path):
    db = str(tmp_path / "snooze.db")
    store = AlertStore(db)
    store.upsert_inventory_threshold(InventoryThreshold("SKU-1", "B0SNZ001", 10))
    alert = AlertRecord(
        alert_id="snz1",
        alert_type="LOW_INVENTORY",
        severity="WARN",
        title="Low",
        asin="B0SNZ001",
        sku="SKU-1",
    )
    store.add_alert(alert)
    assert store.snooze_alert("snz1", 24.0)

    notifier = MagicMock()
    notifier.route = AsyncMock(return_value={"slack": True})
    engine = AlertEngine(store=store, dry_run=True, notifier=notifier)

    with patch("random.random", return_value=0.0):
        count = await engine.check_inventory()

    assert count == 0
    assert store.is_subject_snoozed("LOW_INVENTORY", sku="SKU-1", asin="B0SNZ001")


def test_slack_interactions_endpoint_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret")
    import amazon_mcp.server as srv

    app = srv.mcp.streamable_http_app()
    client = TestClient(app)

    payload = {"type": "block_actions", "actions": []}
    body = _payload_body(payload)
    ts, sig = _sign(body, "test_secret")

    bad = client.post(
        "/slack/interactions",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Signature": "v0=bad",
            "X-Slack-Request-Timestamp": ts,
        },
    )
    assert bad.status_code == 401

    ok = client.post(
        "/slack/interactions",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Signature": sig,
            "X-Slack-Request-Timestamp": ts,
        },
    )
    assert ok.status_code == 200
