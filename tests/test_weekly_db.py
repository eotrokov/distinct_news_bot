from __future__ import annotations

from bot.db import Database


def test_weekly_digest_flag_defaults_and_lists(tmp_path):
    db = Database(str(tmp_path / "w.sqlite3"))
    db.ensure_user(1)
    db.ensure_user(2)
    assert db.is_weekly_digest_enabled(1) is True
    db.set_weekly_digest_enabled(2, False)
    assert db.is_weekly_digest_enabled(2) is False
    # Job only targets users who have channels.
    db.add_source(1, "telegram", "alpha", "@alpha")
    db.add_source(2, "telegram", "beta", "@beta")
    users = db.list_weekly_digest_users()
    assert 1 in users
    assert 2 not in users
