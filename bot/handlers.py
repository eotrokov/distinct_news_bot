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
SEO-дайджест из ваших Telegram-каналов: без дублей, рекламы и оффтопа.

Кнопки:
• Сводка — SEO-новости за период (по реакциям, по блокам)
• Только новое — посты, которых ещё не было в сводках
• Расписание — ежедневная авто-сводка (Trial/Pro/Plus)
• Подписка — план и оплата Stars
• /menu — подробное inline-меню

Команды:
/menu — открыть меню
/add @channel [название] — добавить канал
/add telegram @a @b — несколько каналов сразу
/addlist <ссылка> — папка t.me/addlist/… (затем вручную список @каналов)
/remove <id> — удалить канал
/sources — список каналов
/topic add <тема> — добавить тему-фильтр
/topic del <тема> — удалить тему
/topics — список тем
/topic clear — сбросить все темы
/news — дайджест за период
/news 7 — то же за 7 дней
/news new — только новое
/schedule — авто-сводка по расписанию
/plan — статус подписки
/buy pro | /buy plus — оплата Telegram Stars
/reset — сбросить просмотренное
/delete_me — удалить все ваши данные
/cancel — отменить ввод
/help — эта справка

Блоки: Google и Поиск · Линкбилдинг и E-E-A-T · Инструменты · Аналитика · ИИ в SEO · Контент.

Утро: /schedule on 9:55 — дайджест за вчерашний день (Trial/Pro/Plus).

Trial 7 дней с полным доступом. Дальше Free или Pro/Plus за Stars.

Источники — только публичные Telegram-каналы. Папка addlist: бот берёт название, каналы нужно прислать списком (@name).

Примеры:
/add seonews
/add @ch1 @ch2 https://t.me/ch3
/schedule on 9:55
/buy pro
/news
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    db.ensure_user(user_id)
    sources = db.list_sources(user_id)
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
        type_aliases = {
            "telegram",
            "tg",
            "channel",
            "addlist",
            "folder",
            "list",
        }
        if args and args[0].lower() in type_aliases:
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
        else:
            handles = parse_telegram_handles(joined)
            if len(handles) > 1:
                added, skipped = add_telegram_from_text(db, user_id, joined)
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
        f"Добавлен канал #{source.id}: {source.title}\n"
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
        "Telegram не отдаёт список каналов из папки автоматически.\n"
        "Пришлите публичные @username из папки вручную "
        "(через пробел или с новой строки).\n\n"
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


async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id
    if not db.get_entitlement(user_id).limits().allow_schedule:
        await show_plan_panel(update, context)
        return
    args = list(context.args or [])
    if not args:
        await show_schedule_panel(update, context)
        return

    from bot.schedule import format_schedule_status, parse_schedule_time, parse_tz_offset

    action = args[0].lower()
    try:
        if action in {"on", "enable", "вкл"}:
            if len(args) > 1:
                hour, minute = parse_schedule_time(args[1])
                schedule = db.set_schedule(
                    user_id, enabled=True, hour=hour, minute=minute
                )
            else:
                # Default morning SEO digest: 09:55
                schedule = db.set_schedule(
                    user_id, enabled=True, hour=9, minute=55
                )
        elif action in {"off", "disable", "выкл"}:
            schedule = db.set_schedule(user_id, enabled=False)
        elif action in {"hour", "час", "time", "время"}:
            if len(args) < 2:
                raise ValueError("Формат: /schedule time 9:55")
            hour, minute = parse_schedule_time(args[1])
            schedule = db.set_schedule(
                user_id, hour=hour, minute=minute, enabled=True
            )
        elif action in {"tz", "timezone", "пояс"}:
            if len(args) < 2:
                raise ValueError("Формат: /schedule tz +3")
            offset = parse_tz_offset(args[1])
            schedule = db.set_schedule(user_id, tz_offset_minutes=offset)
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
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id
    db.delete_user_data(user_id)
    clear_awaiting(context)
    await update.message.reply_text(
        "Все ваши данные удалены (каналы, темы, просмотренное, подписка).\n"
        "Нажмите /start, чтобы начать заново.",
        reply_markup=main_reply_keyboard(),
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
            "Формат: /grant <user_id> <trial|free|pro|plus> [дней]"
        )
        return
    try:
        target = int(args[0])
    except ValueError:
        await update.message.reply_text("user_id должен быть числом")
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
        f"Выдано user={target}\n" + format_plan_status(ent)
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
        f"Пользователи: {db.count_users()}\n"
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
        update, context, days=days, only_unseen=only_unseen
    )


async def reset_cursor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id
    cleared = db.clear_seen(user_id)
    db.reset_last_digest_at(user_id)
    await update.message.reply_text(
        f"Просмотренное сброшено ({cleared}). "
        "Кнопка «Только новое» снова покажет эти посты.",
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
