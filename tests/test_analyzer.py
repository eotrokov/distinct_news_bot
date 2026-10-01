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


def test_deduplicate_merges_ru_en_programmatic_story():
    analyzer = NewsAnalyzer()
    ru = _item(
        "Программатик-страницы: как масштабировать SEO",
        "Гайд по programmatic pages и масштабированию контента.",
        url="https://ru.example/p",
        reactions=12,
        body="Гайд по programmatic pages и масштабированию контента.",
    )
    en = _item(
        "Programmatic SEO pages: how to scale",
        "Guide to programmatic pages and scaling SEO content.",
        url="https://en.example/p",
        reactions=40,
        body="Guide to programmatic pages and scaling SEO content.",
    )
    out = analyzer.deduplicate([ru, en])
    assert len(out) == 1
    assert out[0].reactions == 40
    assert len(out[0].urls) == 2


def test_filter_noise_keeps_russian_webinar_recordings():
    """RU SEO channels publish webinar recordings as news — do not drop them."""
    analyzer = NewsAnalyzer()
    items = [
        _item(
            "Триплетные графы для SEO: как Google читает структуру текста",
            "Полная версия вебинара Андрея: текстовое ранжирование в Google "
            "и примеры триплетных графов для SEO-оптимизации текстов.",
            body="Полная версия вебинара Андрея: текстовое ранжирование в Google "
            "и примеры триплетных графов для SEO-оптимизации текстов.",
        ),
        _item(
            "Регистрация на вебинар по покупке ссылок завтра в 19:00",
            "Запишитесь на вебинар прямо сейчас, места ограничены",
            body="Запишитесь на вебинар прямо сейчас, места ограничены",
        ),
    ]
    kept = analyzer.filter_noise(items)
    assert len(kept) == 1
    assert "Триплетные" in kept[0].title


def test_filter_noise_keeps_ru_seo_articles_not_promo_wording():
    """Affiliate / shopping / job-market SEO news must not die on broad substrings."""
    analyzer = NewsAnalyzer()
    keepers = [
        _item(
            "7 стратегий партнёрского маркетинга в эпоху AI-поиска",
            "Статья Kinsta о том, как адаптировать партнёрский сайт к AI-поиску",
            body="Статья Kinsta о том, как адаптировать партнёрский сайт к AI-поиску "
            "и сохранить органический трафик.",
        ),
        _item(
            "Google тестирует кнопку Купить в Flipkart",
            "В тестировании видят кнопку «Купить» на товарах Flipkart в поиске Google",
            body="В тестировании видят кнопку «Купить» на товарах Flipkart в поиске Google.",
        ),
        _item(
            "Посмотрите на эти вакансии: Anthropic SEO Lead",
            "Росс Симондс отмечает рост спроса на SEO/GEO специалистов в AI-компаниях",
            body="Росс Симондс отмечает рост спроса на SEO/GEO специалистов в AI-компаниях.",
        ),
        _item(
            "Как поисковая реклама влияет на органическую выдачу",
            "Разбираем каннибализацию между SEO и контекстной рекламой в Google",
            body="Разбираем каннибализацию между SEO и контекстной рекламой в Google.",
        ),
    ]
    droppers = [
        _item(
            "Партнёрский материал от сервиса ссылок",
            "Партнёрский материал: купите размещение со скидкой только сегодня",
            body="Партнёрский материал: купите размещение со скидкой только сегодня",
        ),
        _item(
            "Реклама\nPBN ссылки со скидкой",
            "Реклама. Скидка на гостевые посты только сегодня",
            body="Реклама. Скидка на гостевые посты только сегодня",
        ),
        _item(
            "Ищу SEO специалиста в агентство",
            "Резюме в личку, зарплата по результатам",
            body="Резюме в личку, зарплата по результатам собеседования",
        ),
    ]
    kept = analyzer.filter_noise(keepers + droppers)
    kept_titles = " ".join(i.title for i in kept)
    assert "партнёрского маркетинга" in kept_titles
    assert "Купить в Flipkart" in kept_titles
    assert "Anthropic" in kept_titles
    assert "поисковая реклама" in kept_titles
    assert "Партнёрский материал" not in kept_titles
    assert "PBN ссылки" not in kept_titles
    assert "Ищу SEO" not in kept_titles


def test_deduplicate_prefers_telegram_over_rss_on_tie():
    """Builtin EN RSS is fetched first; on equal reactions keep the TG post."""
    analyzer = NewsAnalyzer()
    rss = NewsItem(
        title="Google core update confirmed for search ranking",
        url="https://searchengineland.com/core-update",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type="rss",
        source_name="Search Engine Land",
        summary="Google confirmed a core update affecting search ranking.",
        body="Google confirmed a core update affecting search ranking.",
        reactions=0,
        views=0,
    )
    tg = NewsItem(
        title="Google подтвердил core update алгоритма поиска",
        url="https://t.me/shakinru/123",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type="telegram",
        source_name="@shakinru",
        summary="Google подтвердил core update алгоритма поиска в выдаче.",
        body="Google подтвердил core update алгоритма поиска в выдаче.",
        reactions=0,
        views=0,
    )
    out = analyzer.deduplicate([rss, tg])
    assert len(out) == 1
    assert out[0].source_type == "telegram"
    assert "@shakinru" in out[0].source_name or "t.me" in out[0].url



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
