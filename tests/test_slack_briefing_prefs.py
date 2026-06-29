"""Slack briefing display prefs (P1.7b)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from amazon_mcp.integrations.slack_briefing_prefs import (
    SECTION_IDS,
    BriefingDisplayPrefs,
    resolve_prefs,
    save_prefs,
)
from amazon_mcp.tools.notify import set_briefing_prefs


def test_resolve_prefs_defaults_all_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "amazon_mcp.integrations.slack_briefing_prefs.default_prefs_path",
        lambda: tmp_path,
    )
    prefs = resolve_prefs("seller_x", base=tmp_path)
    assert prefs.tenant_id == "seller_x"
    for sid in SECTION_IDS:
        assert prefs.section_enabled(sid) is True


def test_save_and_reload_prefs(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "amazon_mcp.integrations.slack_briefing_prefs.default_prefs_path",
        lambda: tmp_path,
    )
    prefs = BriefingDisplayPrefs(tenant_id="seller_a")
    prefs.sections["wow"] = False
    prefs.sections["chart"] = False
    save_prefs(prefs, base=tmp_path, updated_by="test")
    loaded = resolve_prefs("seller_a", base=tmp_path)
    assert loaded.section_enabled("wow") is False
    assert loaded.section_enabled("chart") is False
    assert loaded.section_enabled("summary") is True


async def test_set_briefing_prefs_tool_get_and_set(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "amazon_mcp.integrations.slack_briefing_prefs.default_prefs_path",
        lambda: tmp_path,
    )
    got = await set_briefing_prefs({"tenant_id": "default"})
    assert got["ok"] is True
    assert "wow" in got["prefs"]["sections"]

    updated = await set_briefing_prefs({
        "tenant_id": "default",
        "sections": {"wow": False, "profit_detail": False},
        "updated_by": "pytest",
    })
    assert updated["ok"] is True
    assert updated["prefs"]["sections"]["wow"] is False
    raw = json.loads((tmp_path / "default.json").read_text(encoding="utf-8"))
    assert raw["sections"]["wow"] is False
