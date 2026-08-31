from __future__ import annotations

from datetime import datetime, timezone

from bot.db import Database
from bot.models import NewsItem


def test_db_sources_and_seen(tmp_path):
    db = Database(str(tmp_path / "bot.sqlite3"))
    user_id = 42
    source = db.add_source(user_id, "telegram", "bbcnews", "@bbcnews")
    assert source.id > 0
    assert len(db.list_sources(user_id)) == 1

    try:
        db.add_source(user_id, "telegram", "bbcnews", "dup")
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

    cleared = db.clear_seen(user_id)
    assert cleared == 2
    assert db.filter_unseen(user_id, ["aaa", "bbb"]) == {"aaa", "bbb"}

    assert db.remove_source(user_id, source.id) is True
    assert db.list_sources(user_id) == []


def test_db_topics(tmp_path):
    db = Database(str(tmp_path / "topics.sqlite3"))
    user_id = 7
    db.add_topic(user_id, "ai")
    db.add_topic(user_id, "marketing")
    assert db.list_topics(user_id) == ["ai", "marketing"]
    rows = db.list_topic_rows(user_id)
    assert len(rows) == 2
    removed = db.remove_topic_by_id(user_id, rows[0][0])
    assert removed == rows[0][1]
    assert db.remove_topic(user_id, "ai") in {True, False}
    assert db.clear_topics(user_id) >= 0
    assert db.list_topics(user_id) == []


def test_db_digest_events_and_stats(tmp_path):
    db = Database(str(tmp_path / "stats.sqlite3"))
    user_id = 100
    group_id = -200
    db.ensure_user(user_id)
    db.ensure_user(group_id)
    db.add_source(user_id, "telegram", "ch1", "@ch1")
    db.add_source(group_id, "telegram", "ch2", "@ch2")
    db.add_topic(user_id, "seo")

    db.log_digest_event(user_id, 5, trigger="manual")
    db.log_digest_event(user_id, 3, trigger="command")
    db.log_digest_event(group_id, 1, trigger="scheduled")

    assert db.count_digest_events_since(7) == 3

    overview = db.get_overview_stats()
    assert overview.total_users == 2
    assert overview.private_users == 1
    assert overview.group_users == 1
    assert overview.total_sources == 2
    assert overview.digests_7d == 3
    assert overview.plan_trial == 2

    rows = db.list_users_with_stats()
    assert len(rows) == 2
    by_id = {row.user_id: row for row in rows}
    assert by_id[user_id].sources_count == 1
    assert by_id[user_id].topics_count == 1
    assert by_id[user_id].digests_7d == 2
    assert by_id[group_id].is_group is True
    assert by_id[group_id].digests_7d == 1
