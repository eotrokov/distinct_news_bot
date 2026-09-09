from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Chat, ReplyKeyboardRemove

from bot.keyboards import BTN_HIDE, main_reply_keyboard, show_reply_keyboard_markup
from bot.menu import (
    REPLY_KB_CLEARED_KEY,
    REPLY_KB_WANTED_KEY,
    ensure_reply_keyboard_cleared,
    hide_bottom_buttons,
    on_reply_button,
    show_bottom_buttons,
)


def _private_update(*, text: str | None = None):
    chat = Chat(id=42, type="private")
    message = AsyncMock()
    message.text = text
    message.chat = chat
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.message = message
    update.effective_message = message
    update.effective_chat = chat
    update.effective_user = SimpleNamespace(id=7)
    update.callback_query = None
    return update, message


@pytest.mark.asyncio
async def test_ensure_reply_keyboard_cleared_once():
    update, message = _private_update()
    context = MagicMock()
    context.user_data = {}

    await ensure_reply_keyboard_cleared(update, context)
    await ensure_reply_keyboard_cleared(update, context)

    assert message.reply_text.await_count == 1
    assert isinstance(
        message.reply_text.await_args.kwargs["reply_markup"], ReplyKeyboardRemove
    )
    assert context.user_data[REPLY_KB_CLEARED_KEY] is True


@pytest.mark.asyncio
async def test_ensure_skips_when_user_wants_keyboard():
    update, message = _private_update()
    context = MagicMock()
    context.user_data = {REPLY_KB_WANTED_KEY: True}

    await ensure_reply_keyboard_cleared(update, context)

    message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_hide_bottom_buttons_removes_keyboard():
    update, message = _private_update()
    context = MagicMock()
    context.user_data = {}

    await hide_bottom_buttons(update, context)

    assert message.reply_text.await_count == 2
    first_kwargs = message.reply_text.await_args_list[0].kwargs
    second_kwargs = message.reply_text.await_args_list[1].kwargs
    assert isinstance(first_kwargs["reply_markup"], ReplyKeyboardRemove)
    assert "скрыты" in message.reply_text.await_args_list[0].args[0].lower()
    show_data = {
        b.callback_data
        for r in second_kwargs["reply_markup"].inline_keyboard
        for b in r
    }
    assert "m:kb:show" in show_data
    assert context.user_data[REPLY_KB_CLEARED_KEY] is True


@pytest.mark.asyncio
async def test_show_bottom_buttons_restores_keyboard():
    update, message = _private_update()
    context = MagicMock()
    context.user_data = {REPLY_KB_CLEARED_KEY: True}

    await show_bottom_buttons(update, context)

    message.reply_text.assert_awaited()
    markup = message.reply_text.await_args.kwargs["reply_markup"]
    labels = {btn.text for row in markup.keyboard for btn in row}
    assert BTN_HIDE in labels
    assert context.user_data[REPLY_KB_CLEARED_KEY] is False
    assert context.user_data[REPLY_KB_WANTED_KEY] is True


@pytest.mark.asyncio
async def test_reply_button_hide_triggers_remove():
    update, message = _private_update(text=BTN_HIDE)
    db = MagicMock()
    context = MagicMock()
    context.user_data = {}
    context.application.bot_data = {"db": db}

    await on_reply_button(update, context)

    db.ensure_user.assert_called_once_with(42)
    assert isinstance(
        message.reply_text.await_args_list[0].kwargs["reply_markup"],
        ReplyKeyboardRemove,
    )


def test_show_reply_keyboard_markup_button():
    kb = show_reply_keyboard_markup()
    assert any(b.callback_data == "m:kb:show" for r in kb.inline_keyboard for b in r)
    reply = main_reply_keyboard()
    assert reply.is_persistent is False
