from __future__ import annotations

from datetime import datetime, timezone

from bot.dedupe import are_near_duplicates, deduplicate, fingerprint_for, normalize_title
from bot.digest import format_digest, parse_add_args
from bot.models import NewsItem


def _item(title: str, url: str = "", source: str = "a") -> NewsItem:
    return NewsItem(
        title=title,
        url=url,
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type="rss",
        source_name=source,
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
