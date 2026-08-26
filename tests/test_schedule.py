from __future__ import annotations

from datetime import datetime, timezone

from bot.db import Database
from bot.schedule import (
    UserSchedule,
    format_schedule_status,
    parse_schedule_time,
    parse_tz_offset,
)


def test_parse_tz_offset():
    assert parse_tz_offset("+3") == 180
    assert parse_tz_offset("UTC+3") == 180
    assert parse_tz_offset("-5") == -300
    assert parse_tz_offset("+03:30") == 210


def test_parse_schedule_time():
    assert parse_schedule_time("9") == (9, 0)
    assert parse_schedule_time("9:55") == (9, 55)
    assert parse_schedule_time("09:55") == (9, 55)
    assert parse_schedule_time("18:30") == (18, 30)


def test_user_schedule_due_now_with_minutes():
    schedule = UserSchedule(
        user_id=1,
        enabled=True,
        hour=9,
        minute=55,
        tz_offset_minutes=180,
        last_schedule_date=None,
    )
    # 06:54 UTC == 09:54 UTC+3 — too early
    early = datetime(2026, 8, 25, 6, 54, tzinfo=timezone.utc)
    assert schedule.due_now(early) is False

    # 06:55 UTC == 09:55 UTC+3 — due
    now = datetime(2026, 8, 25, 6, 55, tzinfo=timezone.utc)
    assert schedule.due_now(now) is True
    assert schedule.local_date_str(now) == "2026-08-25"

    sent = UserSchedule(
        user_id=1,
        enabled=True,
        hour=9,
        minute=55,
        tz_offset_minutes=180,
        last_schedule_date="2026-08-25",
    )
    assert sent.due_now(now) is False


def test_previous_local_day_bounds():
    schedule = UserSchedule(
        user_id=1,
        enabled=True,
        hour=9,
        minute=55,
        tz_offset_minutes=180,
    )
    # 06:55 UTC on Aug 25 == 09:55 UTC+3 → previous day is Aug 24 local
    now = datetime(2026, 8, 25, 6, 55, tzinfo=timezone.utc)
    since, until = schedule.previous_local_day_bounds(now)
    assert since.astimezone(schedule.tzinfo()).isoformat().startswith("2026-08-24T00:00")
    assert until.astimezone(schedule.tzinfo()).isoformat().startswith("2026-08-25T00:00")


def test_db_schedule_roundtrip(tmp_path):
    db = Database(str(tmp_path / "sched.sqlite3"))
    user_id = 99
    schedule = db.set_schedule(
        user_id, enabled=True, hour=9, minute=55, tz_offset_minutes=180
    )
    assert schedule.enabled is True
    assert schedule.hour == 9
    assert schedule.minute == 55
    assert schedule.format_time() == "09:55"
    assert schedule.format_offset() == "UTC+3"

    now = datetime(2026, 8, 25, 6, 56, tzinfo=timezone.utc)  # 09:56 UTC+3
    due = db.list_due_schedules(now)
    assert len(due) == 1
    assert due[0].user_id == user_id

    db.mark_schedule_sent(user_id, "2026-08-25")
    assert db.list_due_schedules(now) == []

    text = format_schedule_status(db.get_schedule(user_id))
    assert "09:55" in text
    assert "UTC+3" in text
    assert "предыдущий" in text
