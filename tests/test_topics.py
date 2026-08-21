from __future__ import annotations

from bot.topics import (
    item_matches_topics,
    item_passes_topic_filters,
    normalize_topic,
    parse_topic_args,
)


def test_normalize_topic():
    assert normalize_topic("  SEO ") == "seo"


def test_parse_topic_args_comma():
    assert parse_topic_args(["seo,", "marketing", "AI"]) == ["seo", "marketing", "ai"]


def test_item_matches_topics():
    assert item_matches_topics("New SEO tools", "", ["seo"])
    assert item_matches_topics("Новости", "продвижение и seo", ["seo"])
    assert not item_matches_topics("Погода завтра", "дождь", ["seo"])
    assert not item_matches_topics("Anything", "", [])  # empty → no match
    # Short token must not match inside unrelated words.
    assert not item_matches_topics("He said nothing", "", ["ai"])
    assert item_matches_topics("New AI overview", "", ["ai"])


def test_item_passes_topic_filters_include_and_exclude():
    # No filters → keep all
    assert item_passes_topic_filters("SEO update", "", include=[], exclude=[])

    # Include whitelist
    assert item_passes_topic_filters("SEO update", "", include=["seo"], exclude=[])
    assert not item_passes_topic_filters("Погода", "дождь", include=["seo"], exclude=[])

    # Exclude blacklist
    assert not item_passes_topic_filters(
        "Крипта снова растёт", "", include=[], exclude=["крипта"]
    )
    assert item_passes_topic_filters(
        "SEO update", "", include=[], exclude=["крипта"]
    )

    # Exclude wins even if include matches
    assert not item_passes_topic_filters(
        "SEO и крипта вместе",
        "",
        include=["seo"],
        exclude=["крипта"],
    )
