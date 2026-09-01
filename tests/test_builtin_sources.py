from __future__ import annotations

from bot.builtin_sources import builtin_rss_sources, merge_sources
from bot.channel_presets import get_rss_preset
from bot.db import Database
from bot.menu import sources_text
from bot.plans import format_plan_status


def test_builtin_rss_matches_seo_preset():
    preset = get_rss_preset("seo-blogs")
    assert preset is not None
    builtins = builtin_rss_sources()
    assert len(builtins) == preset.count
    assert {s.title for s in builtins} == {feed.title for feed in preset.feeds}
    assert all(s.source_type == "rss" for s in builtins)
    assert all(s.id < 0 for s in builtins)


def test_merge_sources_keeps_user_and_skips_duplicates(tmp_path):
    db = Database(str(tmp_path / "builtin.sqlite3"))
    uid = 9
    db.set_plan(uid, "free")
    db.add_source(uid, "telegram", "bbcnews", "@bbcnews")
    ahrefs = next(
        s for s in builtin_rss_sources() if s.title == "Ahrefs Blog"
    )
    db.add_source(uid, "rss", ahrefs.identifier, "Ahrefs Blog")

    merged = merge_sources(db.list_sources(uid))
    titles = [s.title for s in merged]
    assert titles.count("Ahrefs Blog") == 1
    assert "@bbcnews" in {s.title for s in merged} or "bbcnews" in {
        s.identifier for s in merged
    }
    assert len(merged) == 2 + len(builtin_rss_sources()) - 1


def test_free_plan_slots_ignore_builtins(tmp_path):
    db = Database(str(tmp_path / "free-slots.sqlite3"))
    uid = 3
    db.set_plan(uid, "free")
    from bot.sources_ops import add_telegram_channels

    from bot.plans import PLAN_CATALOG

    cap = PLAN_CATALOG["free"].max_sources
    handles = [f"chan{i:04d}" for i in range(cap + 1)]
    added, skipped = add_telegram_channels(db, uid, handles)
    assert len(added) == cap
    assert any("лимит" in s for s in skipped)
    merged = merge_sources(db.list_sources(uid))
    assert len(merged) == cap + len(builtin_rss_sources())


def test_sources_text_lists_builtin_blogs(tmp_path):
    db = Database(str(tmp_path / "src-text.sqlite3"))
    text = sources_text(db, 1)
    assert "слоты плана не занимают" in text
    assert "Ahrefs Blog" in text
    assert "Своих каналов/RSS пока нет" in text


def test_plan_status_mentions_builtin_rss(tmp_path):
    db = Database(str(tmp_path / "plan-rss.sqlite3"))
    db.set_plan(1, "free")
    text = format_plan_status(db.get_entitlement(1))
    assert "⭐️ Подписка: Free" in text
    assert "Источники: до 15" in text
    assert "Сводки: до 10/день" in text
    assert "Окно: до 7 дн." in text
    assert "Расписание: да" in text
    assert "SEO-блоги (RSS): в сводке, слоты не занимают" in text
