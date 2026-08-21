from __future__ import annotations

from datetime import datetime, timezone

from bot.dedupe import are_near_duplicates, deduplicate, fingerprint_for, normalize_title
from bot.digest import format_digest, parse_add_args
from bot.excerpt import build_excerpt
from bot.models import NewsItem


def _item(
    title: str,
    url: str = "",
    source: str = "a",
    summary: str = "",
) -> NewsItem:
    return NewsItem(
        title=title,
        url=url,
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type="rss",
        source_name=source,
        summary=summary,
    )


def test_normalize_title():
    assert normalize_title("  Hello, World!!! ") == "hello world"


def test_fingerprint_stable():
    a = _item("Путин встретился с президентом")
    b = _item("путин встретился с президентом!!!")
    assert fingerprint_for(a) == fingerprint_for(b)


def test_deduplicate_exact_and_near():
    items = [
        _item("Большой взрыв на заводе в Туле", "https://a.example/1", "ria"),
        _item("Большой взрыв на заводе в Туле", "https://b.example/1", "tg"),
        _item("Совершенно другая новость", "https://c.example/2", "rss"),
    ]
    unique = deduplicate(items)
    assert len(unique) == 2
    assert are_near_duplicates(items[0], items[1])


def test_deduplicate_similar_body_across_sources():
    body = (
        "Компания объявила о запуске новой платформы для аналитики поискового трафика "
        "и автоматизации SEO-отчётов на следующий квартал"
    )
    items = [
        _item("Запуск платформы", "https://a.example/1", "ria", summary=body),
        _item(
            "Новый сервис аналитики",
            "https://b.example/2",
            "tg",
            summary=body + " — подробности уточняются",
        ),
    ]
    assert len(deduplicate(items)) == 1


def test_parse_add_args():
    t, ident, title = parse_add_args(["tg", "bbcnews"])
    assert t == "telegram"
    assert ident == "bbcnews"
    assert title.startswith("@")

    t2, ident2, title2 = parse_add_args(["@meduzalive"])
    assert t2 == "telegram"
    assert ident2 == "@meduzalive"
    assert title2.startswith("@")

    try:
        parse_add_args(["rss", "https://example.com/feed.xml"])
        assert False, "expected ValueError for non-telegram"
    except ValueError as exc:
        assert "Telegram" in str(exc)


def test_format_digest_empty():
    chunks = format_digest([], ["timeout"], days=3)
    assert "3 дня" in chunks[0]
    assert "timeout" in chunks[0]


def test_format_digest_with_topics():
    chunks = format_digest(
        [],
        [],
        {"include": ["seo"], "exclude": ["крипта"]},
        days=3,
    )
    assert "seo" in chunks[0]
    assert "крипта" in chunks[0]


def test_format_digest_excerpt_and_link():
    items = [
        _item(
            "Заголовок новости",
            "https://example.com/post/1",
            "РИА",
            summary="Длинный текст поста про событие и детали для читателя ленты.",
        )
    ]
    analysis = {
        "categories": {"🔄 Апдейты алгоритмов": items},
        "stats": {
            "total_processed": 10,
            "final_count": 1,
            "filtered_out": 8,
            "deduped_merged": 1,
        },
    }
    chunks = format_digest(items, [], days=3, analysis=analysis)
    text = chunks[0]
    assert "Дайджест новостей SEO за последние 3 дня" in text
    assert "🔄 Апдейты алгоритмов" in text
    assert "<b>" in text
    assert "источник" in text
    assert "https://example.com/post/1" in text
    assert "Обработано постов: 10" in text
    assert "в дайджест вошло: 1" in text
    assert "отсеяно как реклама/оффтоп: 8" in text
    assert "объединено дублей: 1" in text


def test_format_digest_paginates_by_ten():
    items = [
        _item(
            f"News {i}",
            f"https://example.com/{i}",
            "src",
            summary=f"Summary body for news item number {i} with enough words here.",
        )
        for i in range(25)
    ]
    analysis = {
        "categories": {"🔄 Апдейты алгоритмов": items},
        "stats": {
            "total_processed": 25,
            "final_count": 25,
            "filtered_out": 0,
            "deduped_merged": 0,
        },
    }
    pages = format_digest(items, [], days=3, analysis=analysis, page_size=10)
    assert len(pages) == 3
    assert "Страница 1/3" in pages[0]
    assert "Страница 2/3" in pages[1]
    assert "Страница 3/3" in pages[2]
    assert "Обработано постов: 25" in pages[-1]
    assert "Обработано постов" not in pages[0]
    assert pages[0].count("\n1. ") + pages[0].count("\n2. ") >= 1


def test_build_excerpt_prefers_summary():
    item = _item(
        "Короткий заголовок",
        summary="Короткий заголовок и продолжение текста поста здесь.",
    )
    assert "продолжение" in build_excerpt(item)


def test_parse_days_arg():
    from bot.digest import clamp_digest_days, parse_days_arg

    assert parse_days_arg([]) is None
    assert parse_days_arg(["5"]) == 5
    assert clamp_digest_days(None, 3) == 3
    assert clamp_digest_days(0, 3) == 1
    assert clamp_digest_days(99, 3) == 30
    try:
        parse_days_arg(["99"])
        assert False, "expected ValueError"
    except ValueError:
        pass
