from __future__ import annotations

from bot.summarize import clean_and_summarize, clean_text, first_meaningful_line


def test_strips_hashtags_and_mentions():
    text = "Google запустил новый инструмент #seo #бесплатно@shakinru @channel"
    out = clean_and_summarize(text)
    assert "#" not in out
    assert "@" not in out
    assert "запустил" in out.lower()


def test_skips_intro_fluff():
    text = (
        "Сегодня мы разберем важный кейс. "
        "Компания объявила о запуске новой платформы для аналитики трафика."
    )
    out = clean_and_summarize(text)
    assert "сегодня мы" not in out.lower()
    assert "объявила" in out.lower() or "платформ" in out.lower()


def test_short_text_cleaned():
    assert clean_and_summarize("Короткий факт без мусора") == "Короткий факт без мусора"


def test_first_meaningful_line_skips_greeting():
    text = "Всем привет!\nGoogle представил обновление Search Console."
    assert "представил" in first_meaningful_line(text).lower()


def test_clean_text_removes_channel_tags():
    cleaned = clean_text("Полезный пост #бесплатно@shakinru дальше текст")
    assert "@shakinru" not in cleaned
    assert "#" not in cleaned
