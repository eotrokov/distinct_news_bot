from __future__ import annotations

from datetime import datetime, timezone

from bot.digest import (
    digest_pulse_line,
    format_digest,
    pop_flash_flag,
)


def _item(title: str, *, reactions: int, views: int = 0, summary: str | None = None):
    from bot.models import NewsItem

    return NewsItem(
        title=title,
        url=f"https://example.com/{reactions}-{title}",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type="telegram",
        source_name="src",
        summary=summary or f"{title} with enough words for a digest line here.",
        reactions=reactions,
        views=views,
    )


def test_pop_flash_flag():
    rest, flash = pop_flash_flag(["flash", "7"])
    assert flash is True
    assert rest == ["7"]
    rest, flash = pop_flash_flag(["экспресс"])
    assert flash is True and rest == []
    rest, flash = pop_flash_flag(["7"])
    assert flash is False and rest == ["7"]


def test_digest_pulse_line_hot_and_quiet():
    categories = {
        "🤖 ИИ": [_item("ai", reactions=50)],
        "🔍 Google и Поиск": [_item("google", reactions=20)],
        "🔗 Линкбилдинг": [_item("links", reactions=0)],
    }
    pulse = digest_pulse_line(categories)
    assert pulse.startswith("Пульс:")
    assert "ИИ" in pulse
    assert "Google" in pulse
    assert "Линкбилдинг" in pulse
    assert "💤" in pulse


def test_format_digest_flash_tops_by_reactions():
    analysis = {
        "categories": {
            "🔍 Google и Поиск": [
                _item("Low Google", reactions=2),
                _item("Hot Google", reactions=90, views=5000),
            ],
            "🤖 ИИ": [
                _item("Mid AI", reactions=40),
                _item("Also AI", reactions=10),
                _item("Quiet AI", reactions=1),
                _item("Extra AI", reactions=3),
            ],
            "🔗 Линкбилдинг": [_item("Links", reactions=5)],
        },
        "stats": {
            "total_processed": 7,
            "final_count": 7,
            "filtered_out": 0,
            "deduped_merged": 0,
        },
    }
    pages = format_digest([], [], days=3, analysis=analysis, flash=True)
    assert len(pages) == 1
    text = pages[0]
    assert "⚡ Экспресс: топ-5" in text
    assert "Пульс:" in text
    assert "🔥 90" in text
    assert "👁 5000" in text
    assert "Hot Google" in text
    assert "Quiet AI" not in text  # 6th by heat, trimmed
    assert "Полная: /news" in text
    # Full digest still hides engagement counters on items.
    full = format_digest([], [], days=3, analysis=analysis, flash=False)
    assert "🔥 90" not in full[0]
    assert "Пульс:" in full[0]


def test_format_digest_flash_empty():
    pages = format_digest([], ["timeout"], days=2, flash=True)
    assert "Экспресс" in pages[0]
    assert "горячих постов нет" in pages[0]
    assert "timeout" in pages[0]
