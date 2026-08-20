from __future__ import annotations

from bot.topics import item_matches_topics, normalize_topic, parse_topic_args


def test_normalize_topic():
    assert normalize_topic("  SEO ") == "seo"


def test_parse_topic_args_comma():
    assert parse_topic_args(["seo,", "marketing", "AI"]) == ["seo", "marketing", "ai"]


def test_item_matches_topics():
    assert item_matches_topics("New SEO tools", "", ["seo"])
    assert item_matches_topics("Новости", "продвижение и seo", ["seo"])
    assert not item_matches_topics("Погода завтра", "дождь", ["seo"])
    assert item_matches_topics("Anything", "", [])  # no filter → all match
