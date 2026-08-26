from __future__ import annotations

from datetime import datetime, timezone

from bot.analyzer import NewsAnalyzer, categorize_item
from bot.models import NewsItem


def _item(
    title: str,
    summary: str = "",
    url: str = "https://a.example/1",
    *,
    reactions: int = 0,
    views: int = 0,
    body: str = "",
) -> NewsItem:
    return NewsItem(
        title=title,
        url=url,
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type="telegram",
        source_name="test",
        summary=summary,
        body=body,
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
            "Ищу SEO специалиста в агентство на полную занятость",
            "Резюме в личку, зарплата по результатам собеседования",
        ),
        _item(
            "Google подтвердил обновление поиска",
            "Компания официально подтвердила изменения алгоритма ранжирования в выдаче",
        ),
    ]
    kept = analyzer.filter_noise(items)
    assert len(kept) == 1
    assert "Google" in kept[0].title


def test_filter_relevant_drops_offtopic():
    analyzer = NewsAnalyzer()
    items = [
        _item(
            "Футбольный клуб выиграл чемпионат страны",
            "Матч закончился со счётом три ноль в пользу хозяев поля",
        ),
        _item(
            "Google подтвердил core update",
            "Алгоритм ранжирования в поиске изменился для ряда запросов",
        ),
    ]
    kept = analyzer.filter_relevant(items)
    assert len(kept) == 1
    assert "Google" in kept[0].title


def test_categorize_item_maps_seo_blocks():
    assert (
        categorize_item(
            _item("Google core update", "Алгоритм поиска изменился")
        )
        == "🔍 Google и Поиск"
    )
    assert (
        categorize_item(
            _item("Ahrefs обновил индекс", "DR пересчитан у миллионов сайтов")
        )
        == "🛠 Инструменты и Сервисы"
    )
    assert (
        categorize_item(
            _item("ChatGPT для SEO", "Нейросеть помогает писать контент")
        )
        == "🤖 ИИ в SEO"
    )


def test_deduplicate_prefers_higher_reactions():
    analyzer = NewsAnalyzer()
    low = _item(
        "Google запускает профили издателей в поиске",
        url="https://a.example/1",
        reactions=2,
    )
    high = _item(
        "Google запускает профили издателей в поиске!",
        url="https://b.example/2",
        reactions=40,
        views=9000,
    )
    out = analyzer.deduplicate([low, high])
    assert len(out) == 1
    assert out[0].reactions == 40
    assert len(out[0].urls) == 2
    assert out[0].url == "https://b.example/2"


def test_deduplicate_merges_paraphrased_story_keeps_longer_title():
    analyzer = NewsAnalyzer()
    short = _item(
        "⚡⚡⚡ Google подтвердил core update алгоритма поиска!",
        url="https://a.example/upd",
        reactions=5,
    )
    long = _item(
        "⚠️ Google подтвердил core update алгоритма поиска! "
        "Изменения ранжирования в выдаче затронули коммерческие запросы",
        url="https://b.example/upd",
        reactions=5,
    )
    out = analyzer.deduplicate([short, long])
    assert len(out) == 1
    assert len(out[0].urls) == 2
    assert "коммерческие" in out[0].title


def test_process_groups_by_seo_categories_sorted_by_reactions():
    analyzer = NewsAnalyzer()
    low = _item(
        "Search Console мелкое обновление отчёта",
        "В Search Console появился новый фильтр в отчёте покрытия индексации.",
        url="https://a.example/1",
        reactions=1,
        body="В Search Console появился новый фильтр в отчёте покрытия индексации.",
    )
    mid = _item(
        "Ahrefs выпустил обновление базы ссылок",
        "Ahrefs пересчитал DR у миллионов сайтов после обновления индекса.",
        url="https://a.example/2",
        reactions=10,
        views=1000,
        body="Ahrefs пересчитал DR у миллионов сайтов после обновления индекса.",
    )
    high = _item(
        "Google подтвердил сбой в выдаче поиска",
        "Google подтвердил сбой индексации, страницы выпадали из выдачи на 6 часов.",
        url="https://a.example/3",
        reactions=50,
        body="Google подтвердил сбой индексации, страницы выпадали из выдачи на 6 часов.",
    )
    result = analyzer.process([low, mid, high], period=1, max_sentences=2)
    assert result["stats"]["sort_by"] == "reactions"
    cats = result["categories"]
    assert "🔍 Google и Поиск" in cats
    assert "🛠 Инструменты и Сервисы" in cats
    assert cats["🔍 Google и Поиск"][0].reactions == 50
    tools = cats["🛠 Инструменты и Сервисы"]
    assert [it.reactions for it in tools] == [10, 1]
