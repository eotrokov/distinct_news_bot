from __future__ import annotations

from bot.summarize import clean_and_summarize, clean_text, first_meaningful_line


def test_strips_hashtags_and_mentions():
    text = "Google запустил новый инструмент #seo #бесплатно@shakinru @channel"
    out = clean_and_summarize(text)
    assert "#" not in out
    assert "@channel" not in out
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


def test_multi_sentence_summary():
    text = (
        "Google объявил spam update алгоритма ранжирования для вебмастеров. "
        "Компания заявила, что изменения затронут сайты с манипулятивным контентом. "
        "Вебмастерам рекомендуют проверить Search Console в ближайшие дни."
    )
    out = clean_and_summarize(text, max_sentences=3, max_len=700)
    # Expect more than a single short clip: at least two sentence endings or length.
    assert out.count(".") + out.count("!") + out.count("?") >= 2
    assert len(out) > 80
    assert "spam" in out.lower() or "алгоритм" in out.lower()


def test_first_meaningful_line_skips_greeting():
    text = "Всем привет!\nGoogle представил обновление Search Console."
    assert "представил" in first_meaningful_line(text).lower()


def test_clean_text_removes_channel_tags():
    cleaned = clean_text("Полезный пост #бесплатно@shakinru дальше текст")
    assert "@shakinru" not in cleaned
    assert "#" not in cleaned


def test_example_seo_algorithm():
    raw = (
        "(Тот самый материал, который я обещал) Сегодня мы разберем пошаговый алгоритм "
        "SEO продвижения, включающий в себя исключительно те шаги, которые дают "
        "наибольшую эффективность. Полностью…"
    )
    title = "Пошаговый алгоритм продвижения сайта на 2026 год"
    out = clean_and_summarize(raw, title=title).lower()
    assert "тот самый материал" not in out
    assert "сегодня мы" not in out
    assert "алгоритм" in out
    assert "эффективн" in out
    assert "опубликован" in out or "продвижения" in out


def test_example_neural_layers():
    raw = (
        "Мы много писали про динамические вычисления, когда слои вычисляются в разном "
        "порядке, с циклами и пропусками (например тут и тут). Текущая работа делает "
        "прикольный заход — рассматривает каждый слой нейросети как отдельный "
        "вычислительный блок, что позволяет оптимизировать вычисления."
    )
    out = clean_and_summarize(raw).lower()
    assert "мы много писали" not in out
    assert "прикольный заход" not in out
    assert "рассматривает" in out
    assert "слой" in out or "нейросет" in out


def test_example_google_search_profile():
    title = (
        "Гугл официально запускает профили издателей/создателей контента в поиске, "
        "сначала в США"
    )
    raw = (
        "Поисковый профиль (Search profile) — это специальное пространство, которым "
        "можно делиться, чтобы выделять авторский контент…"
    )
    out = clean_and_summarize(raw, title=title).lower()
    assert "это специальное пространство" not in out
    assert "запускает" in out or "гугл" in out or "google" in out
    assert "профил" in out
