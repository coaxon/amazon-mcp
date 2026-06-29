"""Tests for Stripe webhook handler — signature verification and tier update logic."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import pytest
from unittest.mock import MagicMock, patch

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")


# ── _parse_price_tier_map ─────────────────────────────────────────────────────

class TestPriceTierMap:
    def _map(self, raw: str):
        import importlib
        import amazon_mcp.integrations.stripe_webhook as mod
        with patch.dict(os.environ, {"STRIPE_PRICE_TIER_MAP": raw}):
            importlib.reload(mod)
            return mod._price_tier_map()

    def test_empty_returns_empty_dict(self):
        from amazon_mcp.integrations.stripe_webhook import _price_tier_map
        with patch.dict(os.environ, {"STRIPE_PRICE_TIER_MAP": ""}):
            assert _price_tier_map() == {}

    def test_valid_json_parsed(self):
        from amazon_mcp.integrations.stripe_webhook import _price_tier_map
        raw = json.dumps({"price_starter": "starter", "price_adv": "advanced"})
        with patch.dict(os.environ, {"STRIPE_PRICE_TIER_MAP": raw}):
            mapping = _price_tier_map()
        assert mapping["price_starter"] == "starter"
        assert mapping["price_adv"] == "advanced"

    def test_invalid_tier_filtered_out(self):
        from amazon_mcp.integrations.stripe_webhook import _price_tier_map
        raw = json.dumps({"price_x": "starter", "price_y": "invalid_tier"})
        with patch.dict(os.environ, {"STRIPE_PRICE_TIER_MAP": raw}):
            mapping = _price_tier_map()
        assert "price_x" in mapping
        assert "price_y" not in mapping

    def test_invalid_json_returns_empty(self):
        from amazon_mcp.integrations.stripe_webhook import _price_tier_map
        with patch.dict(os.environ, {"STRIPE_PRICE_TIER_MAP": "not-json"}):
            assert _price_tier_map() == {}

    def test_all_supported_tiers_accepted(self):
        from amazon_mcp.integrations.stripe_webhook import _price_tier_map
        raw = json.dumps({
            "p1": "starter", "p2": "standard", "p3": "advanced", "p4": "global_suite"
        })
        with patch.dict(os.environ, {"STRIPE_PRICE_TIER_MAP": raw}):
            mapping = _price_tier_map()
        assert len(mapping) == 4


# ── _verify_stripe_signature ──────────────────────────────────────────────────

class TestVerifyStripeSignature:
    def _sign(self, payload: bytes, secret: str, ts: int | None = None) -> str:
        if ts is None:
            ts = int(time.time())
        signed = f"{ts}.".encode() + payload
        v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return f"t={ts},v1={v1}"

    def test_valid_signature_passes(self):
        from amazon_mcp.integrations.stripe_webhook import _verify_stripe_signature
        secret = "whsec_test"
        payload = b'{"type":"test"}'
        sig = self._sign(payload, secret)
        assert _verify_stripe_signature(payload, sig, secret) is True

    def test_wrong_secret_fails(self):
        from amazon_mcp.integrations.stripe_webhook import _verify_stripe_signature
        payload = b'{"type":"test"}'
        sig = self._sign(payload, "correct_secret")
        assert _verify_stripe_signature(payload, sig, "wrong_secret") is False

    def test_tampered_payload_fails(self):
        from amazon_mcp.integrations.stripe_webhook import _verify_stripe_signature
        secret = "whsec_test"
        payload = b'{"type":"test"}'
        sig = self._sign(payload, secret)
        assert _verify_stripe_signature(b'{"type":"tampered"}', sig, secret) is False

    def test_old_timestamp_rejected(self):
        from amazon_mcp.integrations.stripe_webhook import _verify_stripe_signature
        secret = "whsec_test"
        payload = b'{"type":"test"}'
        old_ts = int(time.time()) - 400  # >5 min ago
        sig = self._sign(payload, secret, ts=old_ts)
        assert _verify_stripe_signature(payload, sig, secret) is False

    def test_empty_secret_returns_false(self):
        from amazon_mcp.integrations.stripe_webhook import _verify_stripe_signature
        payload = b'{"type":"test"}'
        assert _verify_stripe_signature(payload, "t=1,v1=abc", "") is False

    def test_missing_v1_returns_false(self):
        from amazon_mcp.integrations.stripe_webhook import _verify_stripe_signature
        payload = b'{"type":"test"}'
        assert _verify_stripe_signature(payload, f"t={int(time.time())}", "secret") is False

    def test_malformed_timestamp_returns_false(self):
        from amazon_mcp.integrations.stripe_webhook import _verify_stripe_signature
        payload = b'{"type":"test"}'
        assert _verify_stripe_signature(payload, "t=notanint,v1=abc", "secret") is False


# ── _extract_tenant_id ────────────────────────────────────────────────────────

class TestExtractTenantId:
    def _event(self, metadata: dict) -> dict:
        return {"data": {"object": {"metadata": metadata}}}

    def test_tenant_id_key(self):
        from amazon_mcp.integrations.stripe_webhook import _extract_tenant_id
        e = self._event({"tenant_id": "t-abc"})
        assert _extract_tenant_id(e) == "t-abc"

    def test_amazon_mcp_tenant_id_key(self):
        from amazon_mcp.integrations.stripe_webhook import _extract_tenant_id
        e = self._event({"amazon_mcp_tenant_id": "t-xyz"})
        assert _extract_tenant_id(e) == "t-xyz"

    def test_no_metadata_returns_none(self):
        from amazon_mcp.integrations.stripe_webhook import _extract_tenant_id
        e = {"data": {"object": {}}}
        assert _extract_tenant_id(e) is None


# ── _extract_price_id ─────────────────────────────────────────────────────────

class TestExtractPriceId:
    def test_checkout_session_uses_metadata(self):
        from amazon_mcp.integrations.stripe_webhook import _extract_price_id
        e = {
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {"price_id": "price_abc"}}},
        }
        assert _extract_price_id(e) == "price_abc"

    def test_subscription_updated_extracts_items(self):
        from amazon_mcp.integrations.stripe_webhook import _extract_price_id
        e = {
            "type": "customer.subscription.updated",
            "data": {"object": {
                "metadata": {},
                "items": {"data": [{"price": {"id": "price_standard"}}]},
            }},
        }
        assert _extract_price_id(e) == "price_standard"

    def test_subscription_no_items_returns_none(self):
        from amazon_mcp.integrations.stripe_webhook import _extract_price_id
        e = {
            "type": "customer.subscription.updated",
            "data": {"object": {"metadata": {}, "items": {"data": []}}},
        }
        assert _extract_price_id(e) is None


# ── process_stripe_event ──────────────────────────────────────────────────────

class TestProcessStripeEvent:
    def _price_map(self):
        return json.dumps({"price_standard": "standard", "price_advanced": "advanced"})

    def test_checkout_completed_upgrades_tier(self, tmp_path, monkeypatch):
        from amazon_mcp.integrations.stripe_webhook import process_stripe_event
        monkeypatch.setenv("STRIPE_PRICE_TIER_MAP", self._price_map())

        # Patch set_tenant_tier + set_tenant_quota to avoid file I/O
        with patch("amazon_mcp.integrations.stripe_webhook._handle_tier_update") as mock_update:
            mock_update.return_value = {"tenant_id": "t1", "old_tier": "starter", "new_tier": "standard"}
            e = {
                "type": "checkout.session.completed",
                "data": {"object": {
                    "metadata": {"tenant_id": "t1", "price_id": "price_standard"},
                }},
            }
            result = process_stripe_event(e)

        assert result["ok"] is True
        mock_update.assert_called_once_with("t1", "standard")

    def test_subscription_deleted_downgrades_to_starter(self, monkeypatch):
        from amazon_mcp.integrations.stripe_webhook import process_stripe_event
        monkeypatch.setenv("STRIPE_PRICE_TIER_MAP", self._price_map())

        with patch("amazon_mcp.integrations.stripe_webhook._handle_tier_update") as mock_update:
            mock_update.return_value = {"tenant_id": "t1", "old_tier": "advanced", "new_tier": "starter"}
            e = {
                "type": "customer.subscription.deleted",
                "data": {"object": {"metadata": {"tenant_id": "t1"}}},
            }
            result = process_stripe_event(e)

        assert result["ok"] is True
        mock_update.assert_called_once_with("t1", "starter")

    def test_missing_tenant_id_returns_skipped(self, monkeypatch):
        from amazon_mcp.integrations.stripe_webhook import process_stripe_event
        monkeypatch.setenv("STRIPE_PRICE_TIER_MAP", self._price_map())
        e = {
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {}}},
        }
        result = process_stripe_event(e)
        assert result["ok"] is False
        assert result["skipped"] is True

    def test_unknown_price_id_returns_skipped(self, monkeypatch):
        from amazon_mcp.integrations.stripe_webhook import process_stripe_event
        monkeypatch.setenv("STRIPE_PRICE_TIER_MAP", self._price_map())
        e = {
            "type": "checkout.session.completed",
            "data": {"object": {"metadata": {"tenant_id": "t1", "price_id": "price_unknown"}}},
        }
        result = process_stripe_event(e)
        assert result["ok"] is False
        assert result["skipped"] is True

    def test_unhandled_event_type_is_ok_skipped(self):
        from amazon_mcp.integrations.stripe_webhook import process_stripe_event
        e = {"type": "payment_intent.succeeded", "data": {"object": {}}}
        result = process_stripe_event(e)
        assert result["ok"] is True
        assert result["skipped"] is True


# ── stripe_webhook_endpoint (HTTP) ────────────────────────────────────────────

class TestStripeWebhookEndpoint:
    def _make_request(self, body: bytes, sig: str = "", secret: str = "") -> MagicMock:
        req = MagicMock()

        async def _body():
            return body

        req.body = _body
        headers = {}
        if sig:
            headers["stripe-signature"] = sig
        req.headers = headers
        return req

    def _sign(self, payload: bytes, secret: str) -> str:
        from amazon_mcp.integrations.stripe_webhook import _verify_stripe_signature
        ts = int(time.time())
        signed = f"{ts}.".encode() + payload
        v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return f"t={ts},v1={v1}"

    def test_valid_request_returns_200(self):
        from amazon_mcp.integrations.stripe_webhook import stripe_webhook_endpoint
        body = json.dumps({"type": "unknown_event", "data": {"object": {}}}).encode()
        req = self._make_request(body)

        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": ""}):
            result = asyncio.run(stripe_webhook_endpoint(req))
        assert result.status_code == 200

    def test_invalid_json_returns_400(self):
        from amazon_mcp.integrations.stripe_webhook import stripe_webhook_endpoint
        req = self._make_request(b"not-json")
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": ""}):
            result = asyncio.run(stripe_webhook_endpoint(req))
        assert result.status_code == 400

    def test_invalid_signature_returns_400(self):
        from amazon_mcp.integrations.stripe_webhook import stripe_webhook_endpoint
        body = b'{"type":"test"}'
        req = self._make_request(body, sig="t=1,v1=bad")
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_real"}):
            result = asyncio.run(stripe_webhook_endpoint(req))
        assert result.status_code == 400

    def test_valid_signature_passes(self):
        from amazon_mcp.integrations.stripe_webhook import stripe_webhook_endpoint
        body = json.dumps({"type": "unknown_event", "data": {"object": {}}}).encode()
        secret = "whsec_test123"
        sig = self._sign(body, secret)
        req = self._make_request(body, sig=sig)
        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": secret}):
            result = asyncio.run(stripe_webhook_endpoint(req))
        assert result.status_code == 200
