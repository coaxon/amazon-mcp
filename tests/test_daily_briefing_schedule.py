"""Tests for optional daily briefing schedule."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from amazon_mcp.schedule.daily_briefing_scheduler import (
    DailyBriefingScheduleConfig,
    DailyBriefingScheduler,
    parse_schedule_time,
    seconds_until_next_run,
)


def test_parse_schedule_time_valid():
    assert parse_schedule_time("08:00") == (8, 0)
    assert parse_schedule_time("23:59") == (23, 59)


def test_parse_schedule_time_invalid():
    with pytest.raises(ValueError, match="HH:MM"):
        parse_schedule_time("not-a-time")
    with pytest.raises(ValueError, match="out of range"):
        parse_schedule_time("24:00")


def test_seconds_until_next_run_same_day():
    tz = ZoneInfo("UTC")
    now = datetime(2026, 6, 14, 7, 30, tzinfo=timezone.utc)
    assert seconds_until_next_run(now, 8, 0, tz) == pytest.approx(30 * 60)


def test_seconds_until_next_run_next_day():
    tz = ZoneInfo("UTC")
    now = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc)
    assert seconds_until_next_run(now, 8, 0, tz) == pytest.approx(23 * 3600)


def test_schedule_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("AMAZON_MCP_DAILY_BRIEFING_SCHEDULE_ENABLED", raising=False)
    monkeypatch.delenv("AMAZON_MCP_DAILY_BRIEFING_SCHEDULE_TIME", raising=False)
    monkeypatch.delenv("AMAZON_MCP_DAILY_BRIEFING_SCHEDULE_TZ", raising=False)
    cfg = DailyBriefingScheduleConfig.from_env()
    assert cfg.enabled is False
    assert cfg.time_hhmm == "08:00"
    assert cfg.tz_name == "UTC"


def test_from_env_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("AMAZON_MCP_DAILY_BRIEFING_SCHEDULE_ENABLED", "0")

    async def _noop() -> None:
        pass

    assert DailyBriefingScheduler.from_env(_noop) is None


@pytest.mark.asyncio
async def test_scheduler_fires_after_mocked_delay():
    fired: list[str] = []
    tz = ZoneInfo("UTC")
    now = {"t": datetime(2026, 6, 14, 7, 59, 50, tzinfo=timezone.utc)}
    sched_holder: list[DailyBriefingScheduler] = []

    def now_fn() -> datetime:
        return now["t"]

    async def fake_sleep(delay: float) -> None:
        return None

    async def callback() -> None:
        fired.append("ok")
        await sched_holder[0].stop()

    sched = DailyBriefingScheduler(
        callback,
        hour=8,
        minute=0,
        tz=tz,
        now_fn=now_fn,
        sleep_fn=fake_sleep,
    )
    sched_holder.append(sched)
    await sched.start()
    await asyncio.wait_for(sched._task, timeout=1.0)
    assert fired == ["ok"]


@pytest.mark.asyncio
async def test_scheduler_run_once_now():
    fired: list[int] = []

    async def callback() -> None:
        fired.append(1)

    sched = DailyBriefingScheduler(
        callback,
        hour=8,
        minute=0,
        tz=ZoneInfo("UTC"),
    )
    await sched.run_once_now()
    assert fired == [1]
