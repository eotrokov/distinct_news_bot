from __future__ import annotations

from bot.keyboards import (
    BTN_NEW_ONLY,
    BTN_NEWS,
    BTN_PLAN,
    BTN_SCHEDULE,
    channel_presets_keyboard,
    digest_mode_keyboard,
    digest_page_keyboard,
    main_inline_keyboard,
    main_reply_keyboard,
    plan_keyboard,
    schedule_keyboard,
    sources_keyboard,
    topics_keyboard,
)
from bot.models import Source
from datetime import datetime, timezone


def test_main_keyboards():
    reply = main_reply_keyboard()
    labels = {btn.text for row in reply.keyboard for btn in row}
    assert BTN_NEWS in labels
    assert BTN_NEW_ONLY in labels
    assert BTN_SCHEDULE in labels
    assert BTN_PLAN in labels
    assert "Сброс курсора" not in labels
    inline = main_inline_keyboard()
    assert any(btn.callback_data == "m:news" for row in inline.inline_keyboard for btn in row)
    assert any(
        btn.callback_data == "m:schedule" for row in inline.inline_keyboard for btn in row
    )
    assert any(btn.callback_data == "m:plan" for row in inline.inline_keyboard for btn in row)
    assert not any(
        btn.callback_data == "m:reset" for row in inline.inline_keyboard for btn in row
    )


def test_plan_keyboard():
    kb = plan_keyboard()
    data = {b.callback_data for r in kb.inline_keyboard for b in r}
    assert "m:buy:pro" in data
    assert "m:buy:plus" in data


def test_schedule_keyboard():
    kb = schedule_keyboard(enabled=False)
    data = {b.callback_data for r in kb.inline_keyboard for b in r}
    assert "m:sched:on" in data
    assert "m:sched:t:9:55" in data
    assert "m:sched:tz:180" in data
    kb_on = schedule_keyboard(enabled=True)
    data_on = {b.callback_data for r in kb_on.inline_keyboard for b in r}
    assert "m:sched:off" in data_on


def test_digest_mode_keyboard():
    kb = digest_mode_keyboard()
    data = {b.callback_data for r in kb.inline_keyboard for b in r}
    assert "m:news:top" in data
    assert "m:news:new" in data


def test_sources_and_topics_keyboards():
    source = Source(
        id=3,
        user_id=1,
        source_type="telegram",
        identifier="bbcnews",
        title="@bbcnews",
        created_at=datetime.now(timezone.utc),
    )
    sk = sources_keyboard([source])
    assert any("m:src_del:3" == b.callback_data for r in sk.inline_keyboard for b in r)
    assert any(b.callback_data == "m:src_add" for r in sk.inline_keyboard for b in r)
    assert any(
        b.callback_data == "m:src_presets" for r in sk.inline_keyboard for b in r
    )
    assert any(b.text == "Добавить источник" for r in sk.inline_keyboard for b in r)

    tk = topics_keyboard([(9, "ai")])
    assert any(b.callback_data == "m:topic_del:9" for r in tk.inline_keyboard for b in r)


def test_channel_presets_keyboard():
    kb = channel_presets_keyboard()
    assert any(
        b.callback_data == "m:src_preset:seo-igaming"
        for row in kb.inline_keyboard
        for b in row
    )
    assert any("SEO / iGaming" in b.text for row in kb.inline_keyboard for b in row)


def test_digest_page_keyboard():
    kb = digest_page_keyboard(0, 3)
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert "1/3" in texts
    assert "▶" in texts
    assert "◀" not in texts
    kb2 = digest_page_keyboard(1, 3)
    texts2 = [b.text for r in kb2.inline_keyboard for b in r]
    assert "◀" in texts2 and "▶" in texts2
