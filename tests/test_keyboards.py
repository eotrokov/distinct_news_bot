from __future__ import annotations

from bot.keyboards import (
    BTN_NEWS,
    digest_page_keyboard,
    main_inline_keyboard,
    main_reply_keyboard,
    source_type_keyboard,
    sources_keyboard,
    topics_keyboard,
)
from bot.models import Source
from datetime import datetime, timezone


def test_main_keyboards():
    reply = main_reply_keyboard()
    assert BTN_NEWS in {btn.text for row in reply.keyboard for btn in row}
    inline = main_inline_keyboard()
    assert any(btn.callback_data == "m:news" for row in inline.inline_keyboard for btn in row)


def test_sources_and_topics_keyboards():
    source = Source(
        id=3,
        user_id=1,
        source_type="ria",
        identifier="main",
        title="РИА",
        created_at=datetime.now(timezone.utc),
    )
    sk = sources_keyboard([source])
    assert any("m:src_del:3" == b.callback_data for r in sk.inline_keyboard for b in r)
    assert any(b.callback_data == "m:src_add" for r in sk.inline_keyboard for b in r)

    tk = topics_keyboard([(9, "ai")])
    assert any(b.callback_data == "m:topic_del:9" for r in tk.inline_keyboard for b in r)

    types = source_type_keyboard()
    assert any(b.callback_data == "m:src_type:telegram" for r in types.inline_keyboard for b in r)


def test_digest_page_keyboard():
    kb = digest_page_keyboard(0, 3)
    texts = [b.text for r in kb.inline_keyboard for b in r]
    assert "1/3" in texts
    assert "▶" in texts
    assert "◀" not in texts
    kb2 = digest_page_keyboard(1, 3)
    texts2 = [b.text for r in kb2.inline_keyboard for b in r]
    assert "◀" in texts2 and "▶" in texts2
