from __future__ import annotations

from datetime import datetime, timezone

from bot.analyzer import NewsAnalyzer
from bot.models import NewsItem


def _item(title: str, summary: str = "", url: str = "https://a.example/1") -> NewsItem:
    return NewsItem(
        title=title,
        url=url,
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type="rss",
        source_name="test",
        summary=summary,
    )


def test_filter_noise_removes_ads_and_short():
    analyzer = NewsAnalyzer()
    items = [
        _item("Купить сейчас со скидкой", "Только сегодня акция utm_source=ads"),
        _item("Hi"),
        _item(
            "Google запустил обновление поиска",
            "Компания объявила о запуске нового алгоритма ранжирования в поиске",
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


def test_categorize_and_summary_and_process():
    analyzer = NewsAnalyzer()
    items = [
        _item(
            "Google запустил SEO-обновление",
            "Сегодня мы разберем детали. Компания объявила крупное обновление поиска "
            "для вебмастеров и издателей контента.",
        ),
        _item(
            "Новая нейросеть ускоряет вычисления",
            "Исследователи представили модель, которая оптимизирует слои нейросети.",
        ),
    ]
    result = analyzer.process(items, period=3)
    assert "categories" in result and "stats" in result
    assert result["stats"]["final_count"] >= 1
    assert result["stats"]["period_days"] == 3
    # Summaries should drop intro fluff where possible.
    flat = [it for cat in result["categories"].values() for it in cat]
    assert flat
    assert all(it.summary for it in flat)
