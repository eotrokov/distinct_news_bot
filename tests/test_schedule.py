from __future__ import annotations

from datetime import datetime, timezone

from bot.db import Database
from bot.schedule import UserSchedule, format_schedule_status, parse_tz_offset


def test_parse_tz_offset():
    assert parse_tz_offset("+3") == 180
    assert parse_tz_offset("UTC+3") == 180
    assert parse_tz_offset("-5") == -300
    assert parse_tz_offset("+03:30") == 210


def test_user_schedule_due_now():
    schedule = UserSchedule(
        user_id=1,
        enabled=True,
        hour=9,
        tz_offset_minutes=180,
        last_schedule_date=None,
    )
    # 06:15 UTC == 09:15 UTC+3
    now = datetime(2026, 8, 25, 6, 15, tzinfo=timezone.utc)
    assert schedule.due_now(now) is True
    assert schedule.local_date_str(now) == "2026-08-25"

    sent = UserSchedule(
        user_id=1,
        enabled=True,
        hour=9,
        tz_offset_minutes=180,
        last_schedule_date="2026-08-25",
    )
    assert sent.due_now(now) is False

    wrong_hour = UserSchedule(
        user_id=1,
        enabled=True,
        hour=10,
        tz_offset_minutes=180,
        last_schedule_date=None,
    )
    assert wrong_hour.due_now(now) is False


def test_db_schedule_roundtrip(tmp_path):
    db = Database(str(tmp_path / "sched.sqlite3"))
    user_id = 99
    schedule = db.set_schedule(user_id, enabled=True, hour=8, tz_offset_minutes=180)
    assert schedule.enabled is True
    assert schedule.hour == 8
    assert schedule.format_offset() == "UTC+3"

    now = datetime(2026, 8, 25, 5, 10, tzinfo=timezone.utc)  # 08:10 UTC+3
    due = db.list_due_schedules(now)
    assert len(due) == 1
    assert due[0].user_id == user_id

    db.mark_schedule_sent(user_id, "2026-08-25")
    assert db.list_due_schedules(now) == []

    text = format_schedule_status(db.get_schedule(user_id))
    assert "08:00" in text
    assert "UTC+3" in text
