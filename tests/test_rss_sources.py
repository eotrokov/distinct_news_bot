from __future__ import annotations

from bot.db import Database
from bot.digest import parse_add_args
from bot.rss_presets import SEO_RSS_FEEDS
from bot.sources_ops import add_rss_feeds, add_single_source


def test_parse_add_args_accepts_rss():
    assert parse_add_args(["rss", "https://example.com/feed/", "Example", "SEO"]) == (
        "rss",
        "https://example.com/feed/",
        "Example SEO",
    )
    assert parse_add_args(["feed", "https://example.com/rss.xml"]) == (
        "rss",
        "https://example.com/rss.xml",
        "example.com",
    )
    assert parse_add_args(["https://example.com/feed/"]) == (
        "rss",
        "https://example.com/feed/",
        "example.com",
    )


def test_add_single_rss_source(tmp_path):
    db = Database(str(tmp_path / "rss.sqlite3"))
    source = add_single_source(
        db,
        42,
        "rss",
        "https://example.com/feed/",
        "Example Feed",
    )

    assert source.source_type == "rss"
    assert source.identifier == "https://example.com/feed/"
    assert source.title == "Example Feed"


def test_add_rss_preset_feeds(tmp_path):
    db = Database(str(tmp_path / "rss-preset.sqlite3"))
    added, skipped = add_rss_feeds(db, 42, list(SEO_RSS_FEEDS))

    assert len(added) == len(SEO_RSS_FEEDS)
    assert skipped == []
    sources = db.list_sources(42)
    assert {source.source_type for source in sources} == {"rss"}
    assert {source.identifier for source in sources} == {
        feed.url for feed in SEO_RSS_FEEDS
    }
