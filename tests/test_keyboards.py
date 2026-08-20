from __future__ import annotations

from bot.keyboards import (
    BTN_NEWS,
    BTN_SOURCES,
    main_inline_keyboard,
    main_reply_keyboard,
    sources_keyboard,
    topics_keyboard,
)
from bot.models import Source
from datetime import datetime, timezone


def test_main_keyboards():
    reply = main_reply_keyboard()
    labels = {btn.text for row in reply.keyboard for btn in row}
    assert BTN_NEWS in labels
    assert BTN_SOURCES in labels
    inline = main_inline_keyboard()
    assert any(btn.callback_data == "m:news" for row in inline.inline_keyboard for btn in row)
    assert any(btn.callback_data == "m:sources" for row in inline.inline_keyboard for btn in row)


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

    tk = topics_keyboard([(9, "seo")])
    assert any(b.callback_data == "m:topic_del:9" for r in tk.inline_keyboard for b in r)
