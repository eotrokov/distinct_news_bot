from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram.constants import ChatMemberStatus, ChatType

from bot.chat_scope import (
    group_welcome_text,
    is_group_chat,
    is_private_chat,
    user_can_manage,
    workspace_id,
)


def test_workspace_id_uses_chat():
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type=ChatType.SUPERGROUP)
    )
    assert workspace_id(update) == -100123

    private = SimpleNamespace(
        effective_chat=SimpleNamespace(id=42, type=ChatType.PRIVATE)
    )
    assert workspace_id(private) == 42


def test_is_private_and_group():
    assert is_private_chat(SimpleNamespace(type=ChatType.PRIVATE))
    assert not is_private_chat(SimpleNamespace(type=ChatType.SUPERGROUP))
    assert is_group_chat(SimpleNamespace(type=ChatType.GROUP))
    assert is_group_chat(SimpleNamespace(type=ChatType.SUPERGROUP))
    assert not is_group_chat(SimpleNamespace(type=ChatType.PRIVATE))


def test_group_welcome_mentions_commands():
    text = group_welcome_text("SEO Team")
    assert "SEO Team" in text
    assert "/news" in text
    assert "/add" in text


@pytest.mark.asyncio
async def test_user_can_manage_private_always():
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1, type=ChatType.PRIVATE),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(bot=SimpleNamespace())
    assert await user_can_manage(update, context) is True


@pytest.mark.asyncio
async def test_user_can_manage_group_admin():
    async def get_chat_member(chat_id, user_id):
        return SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=7),
    )
    context = SimpleNamespace(bot=SimpleNamespace(get_chat_member=get_chat_member))
    assert await user_can_manage(update, context) is True

    async def get_member_plain(chat_id, user_id):
        return SimpleNamespace(status=ChatMemberStatus.MEMBER)

    context.bot.get_chat_member = get_member_plain
    assert await user_can_manage(update, context) is False
