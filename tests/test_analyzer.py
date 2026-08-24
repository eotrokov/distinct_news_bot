from __future__ import annotations

from datetime import datetime, timezone

from bot.analyzer import NewsAnalyzer
from bot.models import NewsItem


def _item(
    title: str,
    summary: str = "",
    url: str = "https://a.example/1",
    *,
    reactions: int = 0,
    views: int = 0,
) -> NewsItem:
    return NewsItem(
        title=title,
        url=url,
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type="telegram",
        source_name="test",
        summary=summary,
        reactions=reactions,
        views=views,
    )


def test_filter_noise_removes_ads_and_short():
    analyzer = NewsAnalyzer()
    items = [
        _item("Купить сейчас со скидкой", "Только сегодня акция utm_source=ads"),
        _item("Всем привет", "Не забудьте подписаться и пишите в комментах"),
        _item(
            "Розыгрыш iPhone среди подписчиков канала сегодня вечером",
            "Условия в закрепе",
        ),
        _item("Hi"),
        _item(
            "Google подтвердил обновление поиска",
            "Компания официально подтвердила изменения алгоритма ранжирования в выдаче",
        ),
    ]
    kept = analyzer.filter_noise(items)
    assert len(kept) == 1
    assert "Google" in kept[0].title


def test_deduplicate_merges_similar_titles():
    analyzer = NewsAnalyzer()
    items = [
        _item("Google запускает профили издателей в поиске", url="https://a.example/1"),
        _item(
            "Google запускает профили издателей в поиске!",
            url="https://b.example/2",
        ),
    ]
    out = analyzer.deduplicate(items)
    assert len(out) == 1
    assert len(out[0].urls) == 2


def test_sort_by_reactions_orders_like_weekly():
    analyzer = NewsAnalyzer()
    low = _item(
        "A minor note about a product launch today",
        "Компания представила небольшое обновление интерфейса приложения.",
        url="https://a.example/1",
        reactions=1,
    )
    mid = _item(
        "B mid story about official statement",
        "Компания объявила изменения в правилах модерации контента.",
        url="https://a.example/2",
        reactions=10,
        views=1000,
    )
    high = _item(
        "C breaking announcement from the company",
        "Официально подтвердили запуск новой платформы для издателей.",
        url="https://a.example/3",
        reactions=50,
    )
    result = analyzer.process([low, mid, high], period=7, max_sentences=3)
    assert result["stats"]["sort_by"] == "reactions"
    ranked = result["categories"]["🔥 Главное за неделю"]
    assert [it.title[0] for it in ranked] == ["C", "B", "A"]
