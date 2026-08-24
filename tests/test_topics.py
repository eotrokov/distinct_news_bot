from __future__ import annotations

from bot.topics import item_matches_topics, normalize_topic, parse_topic_args


def test_normalize_topic():
    assert normalize_topic("  AI ") == "ai"


def test_parse_topic_args_comma():
    assert parse_topic_args(["ai,", "marketing", "Finance"]) == [
        "ai",
        "marketing",
        "finance",
    ]


def test_item_matches_topics():
    assert item_matches_topics("New AI tools", "", ["ai"])
    assert item_matches_topics("Новости", "про ai и продукты", ["ai"])
    assert not item_matches_topics("Погода завтра", "дождь", ["ai"])
    assert item_matches_topics("Anything", "", [])  # no filter → all match
