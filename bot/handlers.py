from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.addlist import extract_addlist_slug, fetch_addlist_title, parse_telegram_handles
from bot.db import Database
from bot.digest import parse_add_args
from bot.keyboards import REPLY_BUTTONS, main_inline_keyboard, main_reply_keyboard
from bot.menu import (
    cancel_awaiting,
    get_awaiting,
    on_awaiting_text,
    on_callback,
    on_reply_button,
    send_digest_to_chat,
    set_awaiting,
    show_main_menu,
    show_sources_panel,
    show_topics_panel,
)
from bot.sources_ops import (
    add_single_source,
    add_telegram_from_text,
    format_add_report,
)
from bot.topics import parse_topic_args

logger = logging.getLogger(__name__)

HELP_TEXT = """\
Бот собирает сводку новостей из ваших источников без дублей.

Кнопки:
• снизу экрана — быстрые действия
• /menu — подробное inline-меню

Команды:
/menu — открыть меню
/add <тип> <id|url> [название] — добавить источник
/add telegram @a @b — несколько каналов сразу
/addlist <ссылка> — папка t.me/addlist/… (затем пришлите список @каналов)
/remove <id> — удалить источник
/sources — список источников
/topic add <тема> — добавить тему-фильтр
/topic del <тема> — удалить тему
/topics — список тем
/topic clear — сбросить все темы
/news — сводка с прошлого запроса
/feedback — отзыв или предложение
/reset — сбросить точку прошлого запроса
/cancel — отменить ввод
/help — эта справка

Если темы заданы, в сводку попадают только новости, где встречается хотя бы одна тема (в заголовке или тексте). Без тем — все новости.

Типы источников:
• telegram — публичный канал (@channel) или папка addlist
• ria — лента РИА (main, politics, world, …) или URL RSS
• rss — любой RSS/Atom URL
• facebook — страница (нужен RSSHUB_BASE_URL) или URL RSS
• twitter — аккаунт X/Twitter (нужен RSSHUB_BASE_URL) или URL RSS

Примеры:
/add telegram bbcnews
/add telegram @ch1 @ch2 https://t.me/ch3
/addlist https://t.me/addlist/_0flf9ViWOo0NjNi
/add ria main
/topic add ai
/news
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    if update.effective_user:
        db.ensure_user(update.effective_user.id)
    if update.message:
        await update.message.reply_text(
            "Привет! Я соберу сводку новостей без дублей.\n"
            "Управляйте кнопками внизу или через меню.",
            reply_markup=main_reply_keyboard(),
        )
        await update.message.reply_text(
            "Меню:",
            reply_markup=main_inline_keyboard(),
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(HELP_TEXT, reply_markup=main_reply_keyboard())


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    if update.effective_user:
        db.ensure_user(update.effective_user.id)
    await show_main_menu(update, context)


async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id
    args = list(context.args or [])
    joined = " ".join(args)

    if args and extract_addlist_slug(joined) and "addlist" in joined.lower():
        await begin_addlist_import(update, context, joined)
        return

    try:
        if len(args) >= 2 and args[0].lower() in {
            "telegram",
            "tg",
            "channel",
            "addlist",
            "folder",
            "list",
        }:
            rest = " ".join(args[1:])
            if extract_addlist_slug(rest) and "addlist" in rest.lower():
                await begin_addlist_import(update, context, rest)
                return
            handles = parse_telegram_handles(rest)
            if len(handles) > 1:
                added, skipped = add_telegram_from_text(db, user_id, rest)
                await update.message.reply_text(
                    format_add_report(folder_title=None, added=added, skipped=skipped),
                    reply_markup=main_reply_keyboard(),
                )
                return

        source_type, identifier, title = parse_add_args(args)
        if (
            source_type == "telegram"
            and extract_addlist_slug(identifier)
            and "addlist" in identifier.lower()
        ):
            await begin_addlist_import(update, context, identifier)
            return
        source = add_single_source(db, user_id, source_type, identifier, title)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    await update.message.reply_text(
        f"Добавлен источник #{source.id}: [{source.source_type}] {source.title}\n"
        f"`{source.identifier}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_reply_keyboard(),
    )


async def addlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Формат: /addlist https://t.me/addlist/XXXX\n"
            "Затем пришлите список публичных каналов (@name …)."
        )
        return
    await begin_addlist_import(update, context, " ".join(args))


async def begin_addlist_import(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    raw: str,
) -> None:
    if not update.message or not update.effective_user:
        return
    # If the same message already contains channel handles — add immediately.
    handles = parse_telegram_handles(raw)
    if handles:
        db: Database = context.application.bot_data["db"]
        added, skipped = add_telegram_from_text(
            db, update.effective_user.id, raw
        )
        title = None
        try:
            title = await fetch_addlist_title(raw)
        except ValueError:
            title = None
        await update.message.reply_text(
            format_add_report(folder_title=title, added=added, skipped=skipped),
            reply_markup=main_reply_keyboard(),
        )
        return

    status = await update.message.reply_text("Открываю папку…")
    try:
        title = await fetch_addlist_title(raw)
    except ValueError as exc:
        await status.edit_text(str(exc))
        return

    set_awaiting(
        context,
        {"kind": "addlist_channels", "folder_title": title, "raw": raw},
    )
    await status.edit_text(
        f"Папка: «{title}»\n\n"
        "Пришлите публичные каналы из папки (@username или https://t.me/…)\n"
        "через пробел или с новой строки.\n\n"
        "Пример: @channel1 @channel2\n"
        "/cancel — отмена"
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
    await show_sources_panel(update, context)


async def topic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id
    args = list(context.args or [])
    if not args:
        await show_topics_panel(update, context)
        return

    action = args[0].lower()
    rest = args[1:]

    try:
        if action in {"add", "a", "+"}:
            topics = parse_topic_args(rest)
            added: list[str] = []
            for topic in topics:
                try:
                    db.add_topic(user_id, topic)
                    added.append(topic)
                except ValueError:
                    pass
            if not added:
                await update.message.reply_text("Все указанные темы уже были добавлены.")
                return
            await update.message.reply_text(
                "Добавлены темы: " + ", ".join(added) + "\n"
                "Сейчас активны: " + ", ".join(db.list_topics(user_id))
            )
            return

        if action in {"del", "delete", "remove", "rm", "-"}:
            topics = parse_topic_args(rest)
            removed = [t for t in topics if db.remove_topic(user_id, t)]
            if not removed:
                await update.message.reply_text("Таких тем нет.")
                return
            remaining = db.list_topics(user_id)
            tail = (
                "Остались: " + ", ".join(remaining)
                if remaining
                else "Тем больше нет — /news покажет все новости."
            )
            await update.message.reply_text(
                "Удалены: " + ", ".join(removed) + "\n" + tail
            )
            return

        if action in {"list", "ls", "show"}:
            await show_topics_panel(update, context)
            return

        if action in {"clear", "reset", "all"}:
            count = db.clear_topics(user_id)
            await update.message.reply_text(
                f"Сброшено тем: {count}. Теперь /news без фильтра по темам."
            )
            return

        topics = parse_topic_args(args)
        added = []
        for topic in topics:
            try:
                db.add_topic(user_id, topic)
                added.append(topic)
            except ValueError:
                pass
        if not added:
            await update.message.reply_text("Все указанные темы уже были добавлены.")
            return
        await update.message.reply_text(
            "Добавлены темы: " + ", ".join(added) + "\n"
            "Сейчас активны: " + ", ".join(db.list_topics(user_id))
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def topics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    await show_topics_panel(update, context)


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_digest_to_chat(update, context)


async def reset_cursor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    db.reset_last_digest_at(update.effective_user.id)
    await update.message.reply_text(
        "Точка прошлого запроса сброшена. Следующий /news возьмёт новости "
        "за период DEFAULT_LOOKBACK_HOURS.",
        reply_markup=main_reply_keyboard(),
    )


async def feedback_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    args = context.args or []
    if args:
        db: Database = context.application.bot_data["db"]
        username = update.effective_user.username or ""
        from bot.menu import _notify_admins_about_feedback

        fb = db.add_feedback(update.effective_user.id, username, " ".join(args))
        await update.message.reply_text(
            "Спасибо! Ваш отзыв отправлен администраторам.",
            reply_markup=main_reply_keyboard(),
        )
        await _notify_admins_about_feedback(context, fb)
    else:
        set_awaiting(context, {"kind": "feedback"})
        await update.message.reply_text(
            "Напишите ваш отзыв, предложение или фичреквест.\n"
            "Текст будет отправлен администраторам.\n\n"
            "/cancel — отмена",
            reply_markup=main_reply_keyboard(),
        )


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route plain text to reply-buttons or awaiting input."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text in REPLY_BUTTONS:
        await on_reply_button(update, context)
        return
    if get_awaiting(context):
        await on_awaiting_text(update, context)
        return
    if extract_addlist_slug(text) and "addlist" in text.lower():
        await begin_addlist_import(update, context, text)


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("cancel", cancel_awaiting))
    app.add_handler(CommandHandler("add", add_source))
    app.add_handler(CommandHandler("addlist", addlist_cmd))
    app.add_handler(CommandHandler("remove", remove_source))
    app.add_handler(CommandHandler("sources", list_sources))
    app.add_handler(CommandHandler("topic", topic_cmd))
    app.add_handler(CommandHandler("topics", topics_cmd))
    app.add_handler(CommandHandler("filter", topic_cmd))
    app.add_handler(CommandHandler("filters", topics_cmd))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("digest", news))
    app.add_handler(CommandHandler("reset", reset_cursor))
    app.add_handler(CommandHandler("feedback", feedback_cmd))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^m:"))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_router)
    )
