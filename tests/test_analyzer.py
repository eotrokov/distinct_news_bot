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
        _item("Всем привет", "Не забудьте подписаться и пишите в комментах"),
        _item("Розыгрыш iPhone среди подписчиков канала сегодня вечером", "Условия в закрепе"),
        _item("Hi"),
        _item(
            "Google подтвердил spam update",
            "Компания официально подтвердил изменения алгоритма ранжирования в поиске",
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
            "Google подтвердил spam update",
            "Компания объявил крупный spam update алгоритма ранжирования "
            "для вебмастеров и издателей контента. Подробности на официальном блоге.",
        ),
        _item(
            "Новая нейросеть ускоряет вычисления",
            "Исследователи представили модель llm и нейросеть, которая оптимизирует слои.",
        ),
    ]
    result = analyzer.process(items, period=3)
    assert "categories" in result and "stats" in result
    assert result["stats"]["final_count"] >= 1
    assert result["stats"]["period_days"] == 3
    assert any("Апдейты" in name or "AI" in name for name in result["categories"])
    flat = [it for cat in result["categories"].values() for it in cat]
    assert flat
    assert all(it.summary for it in flat)


def test_extract_summary_skips_stop_phrase_sentences():
    analyzer = NewsAnalyzer()
    item = _item(
        "Апдейт",
        "Всем привет друзья канала. Google подтвердил spam update алгоритма ранжирования.",
    )
    summary = analyzer.extract_summary(item)
    assert "всем привет" not in summary.lower()
    assert "spam update" in summary.lower() or "алгоритм" in summary.lower()
