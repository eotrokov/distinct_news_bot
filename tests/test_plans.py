from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.db import Database
from bot.plans import PLAN_CATALOG, TRIAL_DAYS, UserEntitlement, format_plan_status


def test_trial_entitlement_defaults(tmp_path):
    db = Database(str(tmp_path / "plans.sqlite3"))
    ent = db.get_entitlement(1)
    assert ent.effective_plan() == "trial"
    assert ent.limits().max_sources == PLAN_CATALOG["trial"].max_sources
    assert ent.limits().allow_schedule is True


def test_trial_plan_status_shows_channel_limit(tmp_path):
    db = Database(str(tmp_path / "plan-status.sqlite3"))
    ent = db.get_entitlement(1)

    lines = format_plan_status(ent).splitlines()

    assert lines[:3] == [
        "⭐️ Подписка: Trial",
        "Источники: до 30",
        "SEO-блоги (RSS): в сводке, слоты не занимают",
    ]


def test_trial_expires_to_free():
    started = datetime.now(timezone.utc) - timedelta(days=TRIAL_DAYS + 1)
    ent = UserEntitlement(
        user_id=1,
        plan="trial",
        plan_expires_at=started + timedelta(days=TRIAL_DAYS),
        trial_started_at=started,
        digests_today=0,
        digest_day=None,
    )
    assert ent.effective_plan() == "free"
    assert ent.limits().max_sources == PLAN_CATALOG["free"].max_sources
    assert ent.limits().allow_schedule is PLAN_CATALOG["free"].allow_schedule


def test_digest_quota(tmp_path):
    db = Database(str(tmp_path / "quota.sqlite3"))
    user_id = 5
    db.set_plan(user_id, "free")
    daily = PLAN_CATALOG["free"].max_digests_per_day
    for _ in range(daily):
        ok, _ = db.consume_digest_quota(user_id)
        assert ok is True
    ok, ent = db.consume_digest_quota(user_id)
    assert ok is False
    assert ent.limits().max_digests_per_day == daily


def test_source_limit(tmp_path):
    db = Database(str(tmp_path / "src.sqlite3"))
    user_id = 7
    db.set_plan(user_id, "free")
    from bot.sources_ops import add_telegram_channels

    cap = PLAN_CATALOG["free"].max_sources
    handles = [f"chan{i:04d}" for i in range(cap + 1)]
    added, skipped = add_telegram_channels(db, user_id, handles)
    assert len(added) == cap
    assert any("лимит" in s for s in skipped)


def test_delete_user_data(tmp_path):
    db = Database(str(tmp_path / "del.sqlite3"))
    user_id = 11
    db.add_source(user_id, "telegram", "bbcnews", "@bbcnews")
    db.add_topic(user_id, "ai")
    db.delete_user_data(user_id)
    assert db.list_sources(user_id) == []
    assert db.list_topics(user_id) == []
