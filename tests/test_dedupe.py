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
        source_type="rss",
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
        _item("Большой взрыв на заводе в Туле", "https://a.example/1", "ria"),
        _item("Большой взрыв на заводе в Туле", "https://b.example/1", "tg"),
        _item("Совершенно другая новость", "https://c.example/2", "rss"),
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
            source_name="РИА",
            summary="Длинный текст поста про событие и детали для читателя ленты.",
            reactions=42,
            views=1200,
        )
    ]
    chunks = format_digest(items, [], days=7)
    text = chunks[0]
    assert "Главные новости за 7 дней (по реакциям)" in text
    assert "<b>" in text
    assert "источник" in text
    assert "https://example.com/post/1" in text
    assert "❤️ 42" in text
    assert "👁 1200" in text


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
