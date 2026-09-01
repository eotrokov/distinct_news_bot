"""Chat/workspace helpers for private and group chats.

Private chats keep working: Telegram sets chat.id == user.id, so existing
rows keyed by user_id remain valid. Groups use their negative chat.id as
an independent workspace (sources, topics, schedule, seen items, plan).
"""

from __future__ import annotations

from telegram import Chat, ChatMember, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

MANAGE_STATUSES = frozenset(
    {
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    }
)


def is_private_chat(chat: Chat | None) -> bool:
    return bool(chat and chat.type == ChatType.PRIVATE)


def is_group_chat(chat: Chat | None) -> bool:
    return bool(chat and chat.type in {ChatType.GROUP, ChatType.SUPERGROUP})


def workspace_id(update: Update) -> int | None:
    """Storage key for sources/topics/schedule/digests (= chat.id)."""
    chat = update.effective_chat
    return int(chat.id) if chat is not None else None


def actor_user_id(update: Update) -> int | None:
    user = update.effective_user
    return int(user.id) if user is not None else None


async def user_can_manage(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Anyone in private; only admins/owner in groups."""
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None:
        return False
    if is_private_chat(chat):
        return True
    if not is_group_chat(chat):
        return False
    try:
        member: ChatMember = await context.bot.get_chat_member(chat.id, user.id)
    except Exception:  # noqa: BLE001
        return False
    return member.status in MANAGE_STATUSES


def group_manage_denied_text() -> str:
    return (
        "В группе управлять источниками, темами и расписанием могут только "
        "администраторы чата."
    )


def group_buy_hint() -> str:
    return (
        "Оплата Stars доступна только в личке с ботом.\n"
        "Откройте диалог с ботом и отправьте /buy pro"
    )


def group_welcome_text(chat_title: str | None = None) -> str:
    label = f"«{chat_title}»" if chat_title else "эту группу"
    return (
        f"SEO-дайджест подключён к {label}.\n\n"
        "Команды:\n"
        "• /news — сводка\n"
        "• /add @channel — добавить канал (админы)\n"
        "• /add rss https://site.com/feed/ — RSS (админы)\n"
        "• /sources · /topics · /schedule · /menu\n\n"
        "У каждого чата свои источники и расписание. "
        "Авто-сводка приходит сюда же."
    )
