from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from bot.db import Database
from bot.digest import DigestService, format_digest, parse_add_args
from bot.fetchers.ria import RIA_FEEDS
from bot.fetchers.telegram import normalize_telegram_handle

logger = logging.getLogger(__name__)

HELP_TEXT = """\
Бот собирает сводку новостей из ваших источников без дублей.

Команды:
/add <тип> <id|url> [название] — добавить источник
/remove <id> — удалить источник
/sources — список источников
/news — сводка с прошлого запроса
/reset — сбросить точку прошлого запроса
/help — эта справка

Типы источников:
• telegram — публичный канал (@channel)
• ria — лента РИА (main, politics, world, …) или URL RSS
• rss — любой RSS/Atom URL
• facebook — страница (нужен RSSHUB_BASE_URL) или URL RSS
• twitter — аккаунт X/Twitter (нужен RSSHUB_BASE_URL) или URL RSS

Примеры:
/add telegram bbcnews
/add ria main
/add rss https://example.com/feed.xml Мой фид
/add twitter elonmusk
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    if update.effective_user:
        db.ensure_user(update.effective_user.id)
    if update.message:
        await update.message.reply_text(
            "Привет! Я соберу сводку новостей без дублей.\n\n" + HELP_TEXT
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(HELP_TEXT)


async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id
    try:
        source_type, identifier, title = parse_add_args(context.args or [])
        if source_type == "telegram":
            identifier = normalize_telegram_handle(identifier)
        if source_type == "ria" and not (
            identifier.startswith("http://") or identifier.startswith("https://")
        ):
            key = identifier.lower()
            if key not in RIA_FEEDS:
                known = ", ".join(sorted(RIA_FEEDS))
                raise ValueError(f"Лента РИА: {known} или полный URL RSS")
            identifier = key
        source = db.add_source(user_id, source_type, identifier, title)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    await update.message.reply_text(
        f"Добавлен источник #{source.id}: [{source.source_type}] {source.title}\n"
        f"`{source.identifier}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def remove_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    args = context.args or []
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("Формат: /remove <id>")
        return
    source_id = int(args[0])
    ok = db.remove_source(update.effective_user.id, source_id)
    if ok:
        await update.message.reply_text(f"Источник #{source_id} удалён.")
    else:
        await update.message.reply_text("Источник не найден.")


async def list_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    sources = db.list_sources(update.effective_user.id)
    if not sources:
        await update.message.reply_text("Источников нет. Добавьте через /add")
        return
    lines = ["Ваши источники:"]
    for s in sources:
        lines.append(f"#{s.id} [{s.source_type}] {s.title}\n  {s.identifier}")
    await update.message.reply_text("\n".join(lines))


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    digest: DigestService = context.application.bot_data["digest"]
    user_id = update.effective_user.id
    await update.message.reply_text("Собираю сводку…")
    try:
        items, errors = await digest.collect_for_user(user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Digest failed for user %s", user_id)
        await update.message.reply_text("Не удалось собрать сводку. Попробуйте позже.")
        return

    chunks = format_digest(items, errors)
    for chunk in chunks:
        await update.message.reply_text(chunk)

    digest.mark_digest_delivered(user_id, items)


async def reset_cursor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    db.reset_last_digest_at(update.effective_user.id)
    await update.message.reply_text(
        "Точка прошлого запроса сброшена. Следующий /news возьмёт новости "
        "за период DEFAULT_LOOKBACK_HOURS."
    )


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("add", add_source))
    app.add_handler(CommandHandler("remove", remove_source))
    app.add_handler(CommandHandler("sources", list_sources))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("digest", news))
    app.add_handler(CommandHandler("reset", reset_cursor))
