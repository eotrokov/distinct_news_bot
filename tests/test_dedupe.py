from __future__ import annotations

from datetime import datetime, timezone

from bot.dedupe import are_near_duplicates, deduplicate, fingerprint_for, normalize_title
from bot.digest import format_digest, parse_add_args
from bot.models import NewsItem


def _item(title: str, url: str = "", source: str = "a", **kwargs) -> NewsItem:
    return NewsItem(
        title=title,
        url=url,
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type="telegram",
        source_name=source,
        **kwargs,
    )


def test_normalize_title():
    assert normalize_title("  Hello, World!!! ") == "hello world"


def test_fingerprint_stable():
    a = _item("Путин встретился с президентом")
    b = _item("путин встретился с президентом!!!")
    assert fingerprint_for(a) == fingerprint_for(b)


def test_deduplicate_exact_and_near():
    items = [
        _item("Большой взрыв на заводе в Туле", "https://a.example/1", "ch1"),
        _item("Большой взрыв на заводе в Туле", "https://b.example/1", "ch2"),
        _item("Совершенно другая новость", "https://c.example/2", "ch3"),
    ]
    unique = deduplicate(items)
    assert len(unique) == 2
    assert are_near_duplicates(items[0], items[1])


def test_are_near_duplicates_paraphrased_pitbike_story():
    short = _item(
        "⚡⚡⚡ 16-летняя девушка разбилась насмерть на питбайке по Малоярославцем!",
        "https://a.example/pit",
        "tg1",
    )
    long = _item(
        "⚠️ 16-ЛЕТНЯЯ ДЕВУШКА ПОГИБЛА В ДТП НА ПИТБАЙКЕ! "
        "Смертельная авария произошла вечером в субботу, 22 августа",
        "https://b.example/pit",
        "tg2",
    )
    assert are_near_duplicates(short, long)


def test_are_near_duplicates_google_rewrite():
    a = _item("Google запускает профили издателей в поиске", "https://a.example/g")
    b = _item("В поиске Google появились профили издателей", "https://b.example/g")
    assert are_near_duplicates(a, b)


def test_are_near_duplicates_rejects_unrelated_same_age():
    a = _item(
        "16-летняя девушка победила на олимпиаде по математике в Калуге",
        "https://a.example/math",
    )
    b = _item(
        "16-летняя девушка разбилась насмерть на питбайке по Малоярославцем",
        "https://b.example/pit",
    )
    assert not are_near_duplicates(a, b)


def test_are_near_duplicates_rejects_different_events():
    a = _item("83-летняя женщина пострадала от упавшего дерева в Калуге", "https://a.example/tree")
    b = _item(
        "16-летняя девушка разбилась насмерть на питбайке по Малоярославцем",
        "https://b.example/pit",
    )
    assert not are_near_duplicates(a, b)


def test_parse_add_args():
    t, ident, title = parse_add_args(["tg", "bbcnews"])
    assert t == "telegram"
    assert ident == "bbcnews"
    assert title.startswith("@")


def test_parse_add_args_bare_handle():
    t, ident, title = parse_add_args(["@meduza"])
    assert t == "telegram"
    assert ident == "@meduza"
    assert title == "@meduza"


def test_parse_add_args_rss():
    t, ident, title = parse_add_args(["rss", "https://ahrefs.com/blog/feed/", "Ahrefs", "Blog"])
    assert t == "rss"
    assert ident == "https://ahrefs.com/blog/feed/"
    assert title == "Ahrefs Blog"

    t2, ident2, title2 = parse_add_args(["https://moz.com/posts/rss/blog"])
    assert t2 == "rss"
    assert ident2 == "https://moz.com/posts/rss/blog"
    assert title2 == "moz.com"


def test_parse_add_args_rejects_legacy_types():
    try:
        parse_add_args(["ria", "main"])
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Telegram" in str(exc) or "RSS" in str(exc)


def test_format_digest_empty():
    chunks = format_digest([], ["timeout"], days=3)
    assert "3 дня" in chunks[0]
    assert "timeout" in chunks[0]


def test_format_digest_with_topics():
    chunks = format_digest([], [], ["ai"], days=3)
    assert "ai" in chunks[0]


def test_format_digest_excerpt_and_reactions():
    items = [
        NewsItem(
            title="Заголовок новости",
            url="https://example.com/post/1",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source_type="telegram",
            source_name="SEO",
            summary=(
                "Google подтвердил сбой в выдаче. "
                "Ошибка исправлена и не требует действий вебмастеров."
            ),
            reactions=42,
            views=1200,
        )
    ]
    chunks = format_digest(items, [], days=7)
    text = chunks[0]
    assert "SEO-дайджест за 7 дней (по реакциям)" in text
    assert "<b>🔍 Google и Поиск</b>" in text
    assert "источник" in text
    assert "https://example.com/post/1" in text
    assert "Google подтвердил сбой" in text
    # Engagement counters are not shown in the SEO digest item body.
    assert "❤️ 42" not in text


def test_format_digest_only_unseen_header():
    items = [
        NewsItem(
            title="Свежая новость",
            url="https://example.com/new",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source_type="telegram",
            source_name="ch",
            summary="Текст свежей новости с достаточным числом слов для сводки.",
            reactions=5,
        )
    ]
    analysis = {
        "categories": {"🔍 Google и Поиск": items},
        "stats": {
            "total_processed": 1,
            "final_count": 1,
            "filtered_out": 0,
            "deduped_merged": 0,
            "only_unseen": True,
        },
    }
    pages = format_digest(items, [], days=3, analysis=analysis)
    assert "SEO-дайджест: только новое за 3 дня" in pages[0]


def test_format_digest_only_unseen_empty():
    analysis = {
        "categories": {},
        "stats": {
            "total_processed": 2,
            "final_count": 0,
            "filtered_out": 0,
            "deduped_merged": 0,
            "only_unseen": True,
        },
    }
    pages = format_digest([], [], days=3, analysis=analysis)
    assert "нового нет" in pages[0]
    assert "/reset" in pages[0]


def test_format_digest_paginates_by_page_size():
    items = [
        NewsItem(
            title=f"News {i}",
            url=f"https://example.com/{i}",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source_type="telegram",
            source_name="src",
            summary=f"Summary body for news item number {i} with enough words here.",
            reactions=i,
        )
        for i in range(25)
    ]
    pages = format_digest(items, [], days=3, page_size=10)
    assert len(pages) == 3
    assert "Страница 1/3" in pages[0]
    assert "Страница 2/3" in pages[1]
    assert "Страница 3/3" in pages[2]
