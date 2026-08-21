from __future__ import annotations

from bot.billing import SourceLimitError, ensure_can_add_source
from bot.config import Settings
from bot.db import Database


def _settings(**overrides) -> Settings:
    base = dict(
        telegram_bot_token="x",
        db_path=":memory:",
        log_level="INFO",
        digest_limit=30,
        digest_page_size=10,
        fetch_timeout_seconds=5.0,
        rsshub_base_url=None,
        default_digest_days=3,
        default_lookback_hours=72,
        free_source_limit=2,
        stars_per_extra_source=10,
        paid_slot_days=30,
    )
    base.update(overrides)
    return Settings(**base)


def test_ensure_can_add_source_blocks_over_limit(tmp_path):
    db = Database(str(tmp_path / "bill.sqlite3"))
    settings = _settings(db_path=str(tmp_path / "bill.sqlite3"))
    user_id = 1
    db.add_source(user_id, "rss", "https://a.example/1", "a")
    db.add_source(user_id, "rss", "https://a.example/2", "b")
    try:
        ensure_can_add_source(db, settings, user_id)
        assert False, "expected SourceLimitError"
    except SourceLimitError as exc:
        assert exc.current == 2
        assert exc.limit == 2
        assert exc.stars == 10

    db.add_paid_slot(user_id, stars_paid=10, days=30)
    ensure_can_add_source(db, settings, user_id)  # should not raise
