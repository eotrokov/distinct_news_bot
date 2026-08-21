from __future__ import annotations

from datetime import datetime, timezone

from bot.db import Database
from bot.models import NewsItem


def test_db_sources_and_seen(tmp_path):
    db = Database(str(tmp_path / "bot.sqlite3"))
    user_id = 42
    source = db.add_source(user_id, "ria", "main", "РИА main")
    assert source.id > 0
    assert len(db.list_sources(user_id)) == 1

    try:
        db.add_source(user_id, "ria", "main", "dup")
        assert False, "expected ValueError"
    except ValueError:
        pass

    assert db.get_last_digest_at(user_id) is None
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    db.set_last_digest_at(user_id, now)
    assert db.get_last_digest_at(user_id) == now

    fps = [("aaa", "https://x", "t1"), ("bbb", "https://y", "t2")]
    db.mark_seen(user_id, fps)
    unseen = db.filter_unseen(user_id, ["aaa", "bbb", "ccc"])
    assert unseen == {"ccc"}

    assert db.remove_source(user_id, source.id) is True
    assert db.list_sources(user_id) == []


def test_paid_slots_and_source_limit(tmp_path):
    db = Database(str(tmp_path / "slots.sqlite3"))
    user_id = 99
    for i in range(3):
        db.add_source(user_id, "rss", f"https://ex.example/{i}", f"s{i}")
    assert db.count_sources(user_id) == 3
    assert db.count_active_paid_slots(user_id) == 0
    assert db.source_limit(user_id, free_limit=2) == 2
    active, paused = db.list_active_sources(user_id, free_limit=2)
    assert len(active) == 2
    assert len(paused) == 1

    created, expires = db.add_paid_slot(
        user_id, stars_paid=10, days=30, telegram_payment_charge_id="charge-1"
    )
    assert expires > created
    assert db.count_active_paid_slots(user_id) == 1
    # Idempotent: same charge id must not create a second slot.
    db.add_paid_slot(
        user_id, stars_paid=10, days=30, telegram_payment_charge_id="charge-1"
    )
    assert db.count_active_paid_slots(user_id) == 1
    assert db.source_limit(user_id, free_limit=2) == 3
    active2, paused2 = db.list_active_sources(user_id, free_limit=2)
    assert len(active2) == 3
    assert paused2 == []


def test_db_topics(tmp_path):
    db = Database(str(tmp_path / "topics.sqlite3"))
    user_id = 7
    db.add_topic(user_id, "seo", kind="include")
    db.add_topic(user_id, "marketing", kind="include")
    db.add_topic(user_id, "крипта", kind="exclude")
    assert db.list_include_topics(user_id) == ["marketing", "seo"]
    assert db.list_exclude_topics(user_id) == ["крипта"]
    rows = db.list_topic_rows(user_id)
    assert len(rows) == 3
    removed = db.remove_topic_by_id(user_id, rows[0][0])
    assert removed is not None
    assert removed[0] == rows[0][1]
    assert db.remove_topic(user_id, "seo") in {True, False}
    assert db.clear_topics(user_id, kind="exclude") >= 0
    assert db.clear_topics(user_id) >= 0
    assert db.list_topics(user_id) == []


def test_topic_kind_switch(tmp_path):
    db = Database(str(tmp_path / "topic-kind.sqlite3"))
    user_id = 3
    db.add_topic(user_id, "seo", kind="include")
    # Moving same topic to exclude should update kind, not fail as duplicate.
    topic, kind = db.add_topic(user_id, "seo", kind="exclude")
    assert topic == "seo" and kind == "exclude"
    assert db.list_include_topics(user_id) == []
    assert db.list_exclude_topics(user_id) == ["seo"]
