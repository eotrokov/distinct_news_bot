from __future__ import annotations

from bot.channels import add_channels_bulk, format_bulk_add_result, parse_channel_list
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
        summary_max_sentences=3,
        weekly_top_limit=10,
        weekly_digest_hour_utc=9,
        weekly_digest_weekday=0,
    )
    base.update(overrides)
    return Settings(**base)


def test_parse_channel_list_multi_formats():
    handles = parse_channel_list("@alpha @beta\ngamma, https://t.me/delta")
    assert handles == ["alpha", "beta", "gamma", "delta"]


def test_parse_channel_list_dedupes_and_skips_noise():
    handles = parse_channel_list("telegram @Alpha @alpha канал @beta")
    assert handles == ["alpha", "beta"]


def test_add_channels_bulk_and_limit(tmp_path):
    db = Database(str(tmp_path / "ch.sqlite3"))
    settings = _settings(db_path=str(tmp_path / "ch.sqlite3"), free_source_limit=2)
    user_id = 42
    result = add_channels_bulk(
        db, settings, user_id, ["onechan", "twochan", "threechan"]
    )
    assert len(result["added"]) == 2
    assert result["blocked_by_limit"] == ["threechan"]
    msg = format_bulk_add_result(result)
    assert "Добавлено каналов: 2" in msg
    assert "слотов" in msg.lower() or "Не хватило" in msg

    again = add_channels_bulk(db, settings, user_id, ["onechan", "fourchan"])
    assert again["duplicates"] == ["onechan"]
    assert again["blocked_by_limit"] == ["fourchan"]
