"""Tests for Command Center P4 — write queue, confirm/cancel, audit log."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("AMAZON_MCP_DRY_RUN", "1")


# Patch queue/audit paths to temp dir for isolation
@pytest.fixture(autouse=True)
def _patch_paths(tmp_path, monkeypatch):
    import amazon_mcp.gateway.write_executor as we
    monkeypatch.setattr(we, "_QUEUE_FILE", tmp_path / "queue.jsonl")
    monkeypatch.setattr(we, "_AUDIT_FILE", tmp_path / "audit.jsonl")
    yield


@pytest.fixture(autouse=True)
def _ensure_registry():
    import amazon_mcp.server  # noqa: F401
    yield


from amazon_mcp.gateway.write_executor import (
    cancel_write,
    confirm_write,
    get_audit_log,
    list_pending,
    queue_write,
)
from amazon_mcp.tools.registry import dispatch_domain


# ── queue_write ───────────────────────────────────────────────────────────────

class TestQueueWrite:
    def test_returns_confirm_id(self):
        result = queue_write(
            platform="meli", action="sync_inventory",
            params={"sku": "TEST-SKU", "quantity": 10},
            description="Test queue",
        )
        assert result["ok"] is True
        assert result["confirm_id"].startswith("CC-MEL-")
        assert result["status"] == "PENDING"

    def test_instructions_in_response(self):
        result = queue_write(platform="tiktok", action="sync_price",
                             params={"sku": "SK1", "price": 9.99})
        assert "confirm_id" in result["instructions"]
        assert "confirm_write" in result["instructions"]

    def test_entry_persisted_in_queue(self):
        r = queue_write(platform="amazon", action="sync_inventory",
                        params={"sku": "A1", "quantity": 5})
        cid = r["confirm_id"]
        pending = list_pending()
        assert any(e["confirm_id"] == cid for e in pending)

    def test_preview_stored(self):
        preview = {"effect": "Set stock to 20"}
        r = queue_write(platform="meli", action="sync_inventory",
                        params={}, preview=preview)
        pending = list_pending()
        entry = next(e for e in pending if e["confirm_id"] == r["confirm_id"])
        assert entry["preview"]["effect"] == "Set stock to 20"

    def test_audit_entry_created(self):
        queue_write(platform="meli", action="sync_price", params={"sku": "X"})
        audit = get_audit_log()
        assert any(e.get("audit_event") == "QUEUED" for e in audit)


# ── confirm_write ─────────────────────────────────────────────────────────────

class TestConfirmWrite:
    def test_confirm_pending_entry(self):
        r = queue_write(platform="meli", action="sync_inventory", params={})
        cid = r["confirm_id"]
        result = confirm_write(cid, dry_run=True)
        assert result["ok"] is True
        assert result["status"] == "EXECUTED"
        assert result["confirm_id"] == cid

    def test_confirm_removes_from_pending(self):
        r = queue_write(platform="meli", action="sync_price", params={})
        cid = r["confirm_id"]
        confirm_write(cid, dry_run=True)
        assert not any(e["confirm_id"] == cid for e in list_pending())

    def test_confirm_unknown_id(self):
        result = confirm_write("CC-NO-SUCH-ID", dry_run=True)
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_confirm_already_executed_rejected(self):
        r = queue_write(platform="meli", action="sync_inventory", params={})
        cid = r["confirm_id"]
        confirm_write(cid, dry_run=True)
        result = confirm_write(cid, dry_run=True)  # second confirm
        assert result["ok"] is False
        assert "EXECUTED" in result["error"] or "not PENDING" in result.get("error", "")

    def test_confirm_appends_audit(self):
        r = queue_write(platform="meli", action="sync_inventory", params={})
        confirm_write(r["confirm_id"], dry_run=True)
        audit = get_audit_log()
        events = [e["audit_event"] for e in audit]
        assert "EXECUTED" in events

    def test_dry_run_result(self):
        r = queue_write(platform="meli", action="sync_inventory", params={})
        result = confirm_write(r["confirm_id"], dry_run=True)
        assert result["result"]["dry_run"] is True


# ── cancel_write ──────────────────────────────────────────────────────────────

class TestCancelWrite:
    def test_cancel_pending(self):
        r = queue_write(platform="meli", action="sync_price", params={})
        cid = r["confirm_id"]
        result = cancel_write(cid, reason="user request")
        assert result["ok"] is True
        assert result["status"] == "CANCELLED"

    def test_cancel_removes_from_pending(self):
        r = queue_write(platform="meli", action="sync_price", params={})
        cid = r["confirm_id"]
        cancel_write(cid)
        assert not any(e["confirm_id"] == cid for e in list_pending())

    def test_cancel_unknown_id(self):
        result = cancel_write("CC-NOPE-123")
        assert result["ok"] is False

    def test_cancel_executed_rejected(self):
        r = queue_write(platform="meli", action="sync_inventory", params={})
        confirm_write(r["confirm_id"], dry_run=True)
        result = cancel_write(r["confirm_id"])
        assert result["ok"] is False

    def test_cancel_appends_audit(self):
        r = queue_write(platform="meli", action="sync_price", params={})
        cancel_write(r["confirm_id"], reason="test cancel")
        audit = get_audit_log()
        assert any(e.get("audit_event") == "CANCELLED" for e in audit)


# ── list_pending / get_audit_log ───────────────────────────────────────────────

class TestListAndAudit:
    def test_list_pending_empty_initially(self):
        assert list_pending() == []

    def test_list_pending_multiple(self):
        queue_write(platform="meli", action="sync_inventory", params={}, tenant_id="T1")
        queue_write(platform="meli", action="sync_price", params={}, tenant_id="T1")
        assert len(list_pending(tenant_id="T1")) == 2

    def test_list_pending_filters_by_tenant(self):
        queue_write(platform="meli", action="sync_inventory", params={}, tenant_id="TA")
        queue_write(platform="meli", action="sync_price", params={}, tenant_id="TB")
        assert len(list_pending(tenant_id="TA")) == 1
        assert len(list_pending(tenant_id="TB")) == 1

    def test_list_pending_limit(self):
        for _ in range(5):
            queue_write(platform="meli", action="sync_inventory", params={})
        assert len(list_pending(limit=3)) == 3

    def test_audit_log_empty_initially(self):
        assert get_audit_log() == []

    def test_audit_log_has_queued_event(self):
        queue_write(platform="amazon", action="sync_inventory", params={})
        audit = get_audit_log()
        assert len(audit) >= 1

    def test_audit_log_limit(self):
        for _ in range(10):
            queue_write(platform="meli", action="sync_inventory", params={})
        assert len(get_audit_log(limit=5)) == 5

    def test_audit_log_tenant_filter(self):
        queue_write(platform="meli", action="sync_inventory", params={}, tenant_id="TA")
        queue_write(platform="meli", action="sync_price", params={}, tenant_id="TB")
        audit_a = get_audit_log(tenant_id="TA")
        assert all(e.get("tenant_id") == "TA" for e in audit_a)


# ── Domain tool via dispatch_domain ───────────────────────────────────────────

class TestCommandCenterDomainTool:
    @pytest.mark.asyncio
    async def test_sync_inventory_preview(self):
        raw = await dispatch_domain("command_center", "sync_inventory",
                                    {"platform": "meli", "sku": "SKU-123", "quantity": 10})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert inner.get("preview_only") is True
        assert "instructions" in inner

    @pytest.mark.asyncio
    async def test_sync_price_preview(self):
        raw = await dispatch_domain("command_center", "sync_price",
                                    {"platform": "meli", "sku": "SKU-ABC", "price": 29.99})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert inner.get("preview_only") is True

    @pytest.mark.asyncio
    async def test_sync_inventory_queue_with_confirm(self):
        raw = await dispatch_domain("command_center", "sync_inventory",
                                    {"platform": "meli", "sku": "SKU-Q", "quantity": 5, "confirm": True})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert "confirm_id" in inner
        assert inner["status"] == "PENDING"

    @pytest.mark.asyncio
    async def test_sync_inventory_missing_sku(self):
        raw = await dispatch_domain("command_center", "sync_inventory",
                                    {"platform": "meli", "quantity": 5})
        data = json.loads(raw)
        assert data["ok"] is False or data["data"].get("ok") is False

    @pytest.mark.asyncio
    async def test_list_pending_action(self):
        raw = await dispatch_domain("command_center", "list_pending", {"tenant_id": "default"})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert "pending_count" in inner
        assert isinstance(inner["items"], list)

    @pytest.mark.asyncio
    async def test_audit_log_action(self):
        raw = await dispatch_domain("command_center", "audit_log", {"tenant_id": "default"})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert "entry_count" in inner

    @pytest.mark.asyncio
    async def test_connection_status(self):
        raw = await dispatch_domain("command_center", "connection_status", {})
        data = json.loads(raw)
        assert data["ok"] is True
        inner = data["data"]
        assert inner["phase"] == "P4"
        assert inner["write_executor"] == "ready"
        assert inner["guardrails"]["confirm_gate"] is True

    @pytest.mark.asyncio
    async def test_confirm_write_flow(self):
        # 1. queue
        raw1 = await dispatch_domain("command_center", "sync_inventory",
                                     {"platform": "meli", "sku": "FLOW-SKU", "quantity": 3, "confirm": True})
        d1 = json.loads(raw1)
        cid = d1["data"]["confirm_id"]
        # 2. confirm
        raw2 = await dispatch_domain("command_center", "confirm_write", {"confirm_id": cid})
        d2 = json.loads(raw2)
        assert d2["ok"] is True
        assert d2["data"]["status"] == "EXECUTED"


# ── Feature gate: command_center requires global_suite ────────────────────────

class TestCommandCenterFeatureGate:
    @pytest.mark.asyncio
    async def test_standard_tenant_blocked(self):
        from amazon_mcp.features.feature_gate import set_tenant_tier
        set_tenant_tier("test_std_cc", "standard")
        raw = await dispatch_domain("command_center", "sync_inventory",
                                    {"tenant_id": "test_std_cc", "platform": "meli",
                                     "sku": "X", "quantity": 1})
        data = json.loads(raw)
        assert data.get("ok") is False or data.get("data", {}).get("feature_disabled") is True

    @pytest.mark.asyncio
    async def test_global_suite_tenant_allowed(self):
        from amazon_mcp.features.feature_gate import set_tenant_tier
        set_tenant_tier("test_gs_cc", "global_suite")
        raw = await dispatch_domain("command_center", "connection_status",
                                    {"tenant_id": "test_gs_cc"})
        data = json.loads(raw)
        assert data["ok"] is True
