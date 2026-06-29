"""B17 Slack user ↔ tenant permission model."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from amazon_mcp.gateway.slack_permissions import SlackPermissionStore, get_current_tenant_id


def test_empty_mappings_allow_all(tmp_path):
    path = tmp_path / "perms.json"
    path.write_text(json.dumps({"enforce_permissions": False, "mappings": []}))
    store = SlackPermissionStore(path)
    ok, err = store.authorize(slack_user_id="U_UNKNOWN", tenant_id="default")
    assert ok is True
    assert err == ""


def test_mapped_user_wrong_tenant_denied(tmp_path):
    path = tmp_path / "perms.json"
    path.write_text(json.dumps({
        "enforce_permissions": False,
        "mappings": [{
            "slack_user_id": "U_CEO",
            "tenant_id": "seller_A",
            "allowed_actions": ["confirm_inbound_plan"],
        }],
    }))
    store = SlackPermissionStore(path)
    ok, err = store.authorize(slack_user_id="U_CEO", tenant_id="default", action="confirm_inbound_plan")
    assert ok is False
    assert "seller_A" in err


def test_mapped_user_correct_tenant_allowed(tmp_path):
    path = tmp_path / "perms.json"
    path.write_text(json.dumps({
        "mappings": [{
            "slack_user_id": "U_CEO",
            "tenant_id": "default",
            "allowed_actions": ["confirm_inbound_plan"],
        }],
    }))
    store = SlackPermissionStore(path)
    ok, err = store.authorize(slack_user_id="U_CEO", tenant_id="default", action="confirm_inbound_plan")
    assert ok is True


def test_unmapped_user_denied_when_mappings_exist(tmp_path):
    path = tmp_path / "perms.json"
    path.write_text(json.dumps({
        "mappings": [{
            "slack_user_id": "U_CEO",
            "tenant_id": "default",
            "allowed_actions": ["*"],
        }],
    }))
    store = SlackPermissionStore(path)
    ok, err = store.authorize(slack_user_id="U_STRANGER", tenant_id="default")
    assert ok is False
    assert "not authorized" in err.lower()


def test_get_current_tenant_id_default(monkeypatch):
    monkeypatch.delenv("AMAZON_SELLER_ID", raising=False)
    assert get_current_tenant_id() == "default"
