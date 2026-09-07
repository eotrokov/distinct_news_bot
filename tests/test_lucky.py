from __future__ import annotations

import random
from datetime import datetime, timezone

from bot.dedupe import fingerprint_for
from bot.digest import (
    category_heat_bars,
    format_lucky_card,
    pick_lucky_item,
)
from bot.models import NewsItem


def _item(title: str, *, reactions: int, views: int = 0) -> NewsItem:
    return NewsItem(
        title=title,
        url=f"https://example.com/{title.replace(' ', '-')}",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type="telegram",
        source_name="src",
        summary=f"{title} — достаточно текста для карточки находки.",
        reactions=reactions,
        views=views,
    )


def test_pick_lucky_prefers_hot_pool_and_skips_exclude():
    categories = {
        "🤖 ИИ": [_item("Hot AI", reactions=100), _item("Cold AI", reactions=1)],
        "🔍 Google и Поиск": [_item("Mid Google", reactions=40)],
    }
    hot = categories["🤖 ИИ"][0]
    exclude = {fingerprint_for(hot)}
    rng = random.Random(0)
    picks = {
        pick_lucky_item(categories, exclude=exclude, rng=rng)[1].title
        for _ in range(30)
    }
    assert "Hot AI" not in picks
    assert picks <= {"Cold AI", "Mid Google"}


def test_pick_lucky_empty():
    assert pick_lucky_item({}) is None


def test_category_heat_bars():
    categories = {
        "🤖 ИИ": [_item("a", reactions=80)],
        "🔍 Google и Поиск": [_item("b", reactions=20)],
        "🔗 Линкбилдинг": [_item("c", reactions=0)],
    }
    bars = category_heat_bars(categories, width=8)
    assert "Жарче всего:" in bars
    assert "ИИ" in bars
    assert "█" in bars
    assert "░" in bars


def test_format_lucky_card_includes_engagement_and_bars():
    item = _item("Big Update", reactions=55, views=1200)
    categories = {
        "🔍 Google и Поиск": [item, _item("Other", reactions=10)],
        "🤖 ИИ": [_item("AI", reactions=30)],
    }
    card = format_lucky_card(
        "🔍 Google и Поиск",
        item,
        days=3,
        categories=categories,
        opener="🎲 Вот что выпало:",
    )
    assert "🎲 Вот что выпало:" in card
    assert "за 3 дня" in card
    assert "Big Update" in card
    assert "🔥 55" in card
    assert "👁 1200" in card
    assert "источник" in card
    assert "Жарче всего:" in card
    assert "<pre>" in card
