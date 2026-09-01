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
from bot.chat_scope import (
    group_buy_hint,
    group_manage_denied_text,
    group_welcome_text,
    is_group_chat,
    is_private_chat,
    user_can_manage,
    workspace_id,
)
from bot.db import Database
from bot.digest import parse_add_args, parse_days_arg
from bot.keyboards import REPLY_BUTTONS, main_inline_keyboard, main_reply_keyboard
from bot.menu import (
    cancel_awaiting,
    clear_awaiting,
    get_awaiting,
    on_awaiting_text,
    on_callback,
    on_reply_button,
    send_digest_to_chat,
    set_awaiting,
    show_main_menu,
    show_plan_panel,
    show_schedule_panel,
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
SEO-дайджест из Telegram-каналов и RSS-лент: без дублей, рекламы и оффтопа.

Работает в личке и в групповых чатах. В группе у чата свои каналы и расписание;
настраивать могут администраторы. Оплата Stars — только в личке с ботом.

Команды:
/menu — меню
/add @channel — добавить Telegram-канал
/add rss https://site.com/feed/ Название — добавить RSS
/add @a @b — несколько каналов
/addlist <ссылка> — папка t.me/addlist/…
/remove <id> — удалить источник
/sources — список источников
/topic add <тема> — тема-фильтр
/topics — список тем
/news — дайджест
/news 7 — за 7 дней
/news new — только новое
/schedule on 9 — авто-сводка в этот чат
/plan — статус подписки
/buy pro — оплата Stars (личка)
/reset — сбросить просмотренное
/delete_me — удалить данные этого чата
/help — справка

Блоки: Google · Линкбилдинг · Инструменты · Аналитика · ИИ · Контент.

Утро: /schedule on 9:55 — дайджест за вчера (в личке или группе).
Добавьте бота в группу → /start → /add @channel → /news.
"""


def _reply_kb(update: Update):
    if is_private_chat(update.effective_chat):
        return main_reply_keyboard()
    return None


async def _deny_if_cannot_manage(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Return True if the user may NOT manage (and a reply was sent)."""
    if await user_can_manage(update, context):
        return False
    if update.effective_message:
        await update.effective_message.reply_text(group_manage_denied_text())
    return True



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    if not update.message or not update.effective_chat:
        return
    chat_id = workspace_id(update)
    if chat_id is None:
        return
    db.ensure_user(chat_id)

    if is_group_chat(update.effective_chat):
        if await _deny_if_cannot_manage(update, context):
            return
        title = update.effective_chat.title
        sources = db.list_sources(chat_id)
        await update.message.reply_text(group_welcome_text(title))
        await update.message.reply_text(
            "Меню:" if sources else "Добавьте источник: /add @channel или /add rss https://site.com/feed/",
            reply_markup=main_inline_keyboard(),
        )
        return

    sources = db.list_sources(chat_id)
    if not sources:
        from bot.keyboards import ONBOARD_PROMPT
        from bot.menu import set_awaiting

        set_awaiting(context, {"kind": "onboard"})
        await update.message.reply_text(
            ONBOARD_PROMPT,
            reply_markup=main_reply_keyboard(),
        )
        return

    await update.message.reply_text(
        "Снова рады вас видеть. Нажмите «Сводка» или «Только новое».",
        reply_markup=main_reply_keyboard(),
    )
    await update.message.reply_text(
        "Меню:",
        reply_markup=main_inline_keyboard(),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(HELP_TEXT, reply_markup=_reply_kb(update))


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    chat_id = workspace_id(update)
    if chat_id is not None:
        db.ensure_user(chat_id)
    await show_main_menu(update, context)


async def add_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    if await _deny_if_cannot_manage(update, context):
        return
    db: Database = context.application.bot_data["db"]
    chat_id = workspace_id(update)
    if chat_id is None:
        return
    db.ensure_user(chat_id)
    args = list(context.args or [])
    joined = " ".join(args)
    kb = _reply_kb(update)

    if args and extract_addlist_slug(joined) and "addlist" in joined.lower():
        await begin_addlist_import(update, context, joined)
        return

    try:
        type_aliases = {
            "telegram",
            "tg",
            "channel",
            "addlist",
            "folder",
            "list",
            "rss",
            "feed",
        }
        if args and args[0].lower() in type_aliases:
            rest = " ".join(args[1:])
            if extract_addlist_slug(rest) and "addlist" in rest.lower():
                await begin_addlist_import(update, context, rest)
                return
            handles = parse_telegram_handles(rest)
            if len(handles) > 1:
                added, skipped = add_telegram_from_text(db, chat_id, rest)
                await update.message.reply_text(
                    format_add_report(folder_title=None, added=added, skipped=skipped),
                    reply_markup=kb,
                )
                return
        else:
            handles = parse_telegram_handles(joined)
            if len(handles) > 1:
                added, skipped = add_telegram_from_text(db, chat_id, joined)
                await update.message.reply_text(
                    format_add_report(folder_title=None, added=added, skipped=skipped),
                    reply_markup=kb,
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
        source = add_single_source(db, chat_id, source_type, identifier, title)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    await update.message.reply_text(
        f"Добавлен {'RSS-источник' if source.source_type == 'rss' else 'канал'} "
        f"#{source.id}: {source.title}\n"
        f"`{source.identifier}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )


async def addlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    if await _deny_if_cannot_manage(update, context):
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Формат: /addlist https://t.me/addlist/XXXX\n"
            "Telegram не отдаёт список каналов папки ботам — "
            "затем пришлите публичные @username вручную."
        )
        return
    await begin_addlist_import(update, context, " ".join(args))


async def begin_addlist_import(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    raw: str,
) -> None:
    if not update.message or not update.effective_chat:
        return
    if await _deny_if_cannot_manage(update, context):
        return
    chat_id = workspace_id(update)
    if chat_id is None:
        return
    kb = _reply_kb(update)
    handles = parse_telegram_handles(raw)
    if handles:
        db: Database = context.application.bot_data["db"]
        db.ensure_user(chat_id)
        added, skipped = add_telegram_from_text(db, chat_id, raw)
        title = None
        try:
            title = await fetch_addlist_title(raw)
        except ValueError:
            title = None
        await update.message.reply_text(
            format_add_report(folder_title=title, added=added, skipped=skipped),
            reply_markup=kb,
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
    hint = (
        "Пришлите публичные @username из папки вручную "
        "(через пробел или с новой строки)."
        if is_private_chat(update.effective_chat)
        else "В группе пришлите: /add @ch1 @ch2 …"
    )
    await status.edit_text(
        f"Папка: «{title}»\n\n"
        "Telegram не отдаёт список каналов из папки автоматически.\n"
        f"{hint}\n\n"
        "Пример: @channel1 @channel2\n"
        "/cancel — отмена"
    )


async def remove_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    if await _deny_if_cannot_manage(update, context):
        return
    db: Database = context.application.bot_data["db"]
    chat_id = workspace_id(update)
    if chat_id is None:
        return
    args = context.args or []
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("Формат: /remove <id>")
        return
    source_id = int(args[0])
    ok = db.remove_source(chat_id, source_id)
    if ok:
        await update.message.reply_text(f"Источник #{source_id} удалён.")
    else:
        await update.message.reply_text("Источник не найден.")


async def list_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    await show_sources_panel(update, context)


async def topic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    db: Database = context.application.bot_data["db"]
    chat_id = workspace_id(update)
    if chat_id is None:
        return
    db.ensure_user(chat_id)
    args = list(context.args or [])
    if not args:
        await show_topics_panel(update, context)
        return

    action = args[0].lower()
    rest = args[1:]

    if action not in {"list", "ls", "show"}:
        if await _deny_if_cannot_manage(update, context):
            return

    try:
        if action in {"add", "a", "+"}:
            topics = parse_topic_args(rest)
            added: list[str] = []
            for topic in topics:
                try:
                    db.add_topic(chat_id, topic)
                    added.append(topic)
                except ValueError:
                    pass
            if not added:
                await update.message.reply_text("Все указанные темы уже были добавлены.")
                return
            await update.message.reply_text(
                "Добавлены темы: " + ", ".join(added) + "\n"
                "Сейчас активны: " + ", ".join(db.list_topics(chat_id))
            )
            return

        if action in {"del", "delete", "remove", "rm", "-"}:
            topics = parse_topic_args(rest)
            removed = [t for t in topics if db.remove_topic(chat_id, t)]
            if not removed:
                await update.message.reply_text("Таких тем нет.")
                return
            remaining = db.list_topics(chat_id)
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
            count = db.clear_topics(chat_id)
            await update.message.reply_text(
                f"Сброшено тем: {count}. Теперь /news без фильтра по темам."
            )
            return

        # Shorthand: /topic ai
        topics = parse_topic_args(args)
        added = []
        for topic in topics:
            try:
                db.add_topic(chat_id, topic)
                added.append(topic)
            except ValueError:
                pass
        if not added:
            await update.message.reply_text(
                "Все указанные темы уже были добавлены.\n"
                "Сейчас активны: " + ", ".join(db.list_topics(chat_id))
            )
            return
        await update.message.reply_text(
            "Добавлены темы: " + ", ".join(added) + "\n"
            "Сейчас активны: " + ", ".join(db.list_topics(chat_id))
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def topics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_topics_panel(update, context)


async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    db: Database = context.application.bot_data["db"]
    chat_id = workspace_id(update)
    if chat_id is None:
        return
    db.ensure_user(chat_id)
    if not db.get_entitlement(chat_id).limits().allow_schedule:
        await show_plan_panel(update, context)
        return
    args = list(context.args or [])
    if not args:
        await show_schedule_panel(update, context)
        return
    if await _deny_if_cannot_manage(update, context):
        return

    from bot.schedule import format_schedule_status, parse_schedule_time, parse_tz_offset

    action = args[0].lower()
    try:
        if action in {"on", "enable", "вкл"}:
            if len(args) > 1:
                hour, minute = parse_schedule_time(args[1])
                schedule = db.set_schedule(
                    chat_id, enabled=True, hour=hour, minute=minute
                )
            else:
                schedule = db.set_schedule(
                    chat_id, enabled=True, hour=9, minute=55
                )
        elif action in {"off", "disable", "выкл"}:
            schedule = db.set_schedule(chat_id, enabled=False)
        elif action in {"hour", "час", "time", "время"}:
            if len(args) < 2:
                raise ValueError("Формат: /schedule time 9:55")
            hour, minute = parse_schedule_time(args[1])
            schedule = db.set_schedule(
                chat_id, hour=hour, minute=minute, enabled=True
            )
        elif action in {"tz", "timezone", "пояс"}:
            if len(args) < 2:
                raise ValueError("Формат: /schedule tz +3")
            offset = parse_tz_offset(args[1])
            schedule = db.set_schedule(chat_id, tz_offset_minutes=offset)
        else:
            raise ValueError(
                "Команды: /schedule on [время], /schedule off, "
                "/schedule time 9:55, /schedule tz +3"
            )
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    from bot.keyboards import schedule_keyboard

    await update.message.reply_text(
        format_schedule_status(schedule),
        reply_markup=schedule_keyboard(enabled=schedule.enabled),
    )


async def plan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_plan_panel(update, context)


async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not is_private_chat(update.effective_chat):
        await update.message.reply_text(group_buy_hint())
        return
    args = list(context.args or [])
    if not args or args[0].lower() not in {"pro", "plus"}:
        await update.message.reply_text("Формат: /buy pro или /buy plus")
        return
    from bot.payments import send_plan_invoice

    try:
        await send_plan_invoice(update, context, args[0].lower())
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def delete_me_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    if await _deny_if_cannot_manage(update, context):
        return
    db: Database = context.application.bot_data["db"]
    chat_id = workspace_id(update)
    if chat_id is None:
        return
    db.delete_user_data(chat_id)
    clear_awaiting(context)
    where = "этого чата" if is_group_chat(update.effective_chat) else "ваши"
    await update.message.reply_text(
        f"Все данные {where} удалены (источники, темы, просмотренное, подписка).\n"
        "Нажмите /start, чтобы начать заново.",
        reply_markup=_reply_kb(update),
    )


def _require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    from bot.config import Settings

    settings: Settings = context.application.bot_data["settings"]
    user = update.effective_user
    return bool(user and user.id in settings.admin_user_ids)


async def grant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not _require_admin(update, context):
        await update.message.reply_text("Недостаточно прав.")
        return
    args = list(context.args or [])
    if len(args) < 2:
        await update.message.reply_text(
            "Формат: /grant <user_or_chat_id> <trial|free|pro|plus> [дней]\n"
            "Для группы укажите chat_id (отрицательный)."
        )
        return
    try:
        target = int(args[0])
    except ValueError:
        await update.message.reply_text("id должен быть числом")
        return
    plan = args[1].lower()
    if plan not in {"trial", "free", "pro", "plus"}:
        await update.message.reply_text("План: trial, free, pro, plus")
        return
    days = int(args[2]) if len(args) > 2 else 30
    from datetime import datetime, timedelta, timezone

    from bot.plans import format_plan_status

    db: Database = context.application.bot_data["db"]
    expires = None
    if plan in {"pro", "plus", "trial"}:
        expires = datetime.now(timezone.utc) + timedelta(days=days)
    ent = db.set_plan(target, plan, expires_at=expires)
    await update.message.reply_text(
        f"Выдано id={target}\n" + format_plan_status(ent)
    )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not _require_admin(update, context):
        await update.message.reply_text("Недостаточно прав.")
        return
    db: Database = context.application.bot_data["db"]
    await update.message.reply_text(
        "📊 Статистика\n"
        f"Пользователи/чаты: {db.count_users()}\n"
        f"Каналы: {db.count_sources()}\n"
        f"Платящие (pro/plus): {db.count_paid_users()}"
    )


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    args = list(context.args or [])
    only_unseen = False
    days: int | None = None
    if args and args[0].lower() in {"new", "unseen", "новое", "novoe"}:
        only_unseen = True
        args = args[1:]
    try:
        days = parse_days_arg(args)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await send_digest_to_chat(
        update, context, days=days, only_unseen=only_unseen, trigger="command"
    )


async def reset_cursor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    if await _deny_if_cannot_manage(update, context):
        return
    db: Database = context.application.bot_data["db"]
    chat_id = workspace_id(update)
    if chat_id is None:
        return
    cleared = db.clear_seen(chat_id)
    db.reset_last_digest_at(chat_id)
    await update.message.reply_text(
        f"Просмотренное сброшено ({cleared}). "
        "«Только новое» снова покажет эти посты.",
        reply_markup=_reply_kb(update),
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
    # In groups with privacy mode the bot rarely sees plain text; ignore noise.
    if is_group_chat(update.effective_chat):
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
    app.add_handler(CommandHandler("schedule", schedule_cmd))
    app.add_handler(CommandHandler("plan", plan_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("delete_me", delete_me_cmd))
    app.add_handler(CommandHandler("grant", grant_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("reset", reset_cursor))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^m:"))
    from bot.payments import on_pre_checkout, on_successful_payment
    from telegram.ext import PreCheckoutQueryHandler

    app.add_handler(PreCheckoutQueryHandler(on_pre_checkout))
    app.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_router)
    )
