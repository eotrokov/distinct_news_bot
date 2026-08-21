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
    PreCheckoutQueryHandler,
    filters,
)

from bot.billing import (
    PAYLOAD_BUY_SLOT,
    PAYLOAD_BUY_SLOT_ADD,
    SourceLimitError,
    dump_pending_source,
    ensure_can_add_source,
    parse_pending_source,
    send_slot_invoice,
)
from bot.config import Settings
from bot.db import Database
from bot.digest import parse_add_args, parse_days_arg
from bot.fetchers.ria import RIA_FEEDS
from bot.fetchers.telegram import normalize_telegram_handle
from bot.keyboards import REPLY_BUTTONS, main_inline_keyboard, main_reply_keyboard
from bot.menu import (
    _sources_markup,
    cancel_awaiting,
    get_awaiting,
    on_awaiting_text,
    on_callback,
    on_reply_button,
    send_digest_to_chat,
    show_main_menu,
    show_sources_panel,
    show_topics_panel,
    topics_text,
)
from bot.topics import parse_topic_args

logger = logging.getLogger(__name__)

HELP_TEXT = """\
Бот собирает одну выжимку (портянку) постов из ваших источников —
не нужно заходить в каждый канал отдельно. Листаете ленту, по ссылке
открываете оригинал, если нужно. Похожие посты из разных каналов схлопываются.

Кнопки:
• снизу экрана — быстрые действия
• /menu — подробное inline-меню
• если новостей >10 — стрелки ◀ ▶ в сообщении выжимки

Лимиты:
• до 20 источников бесплатно
• дальше — 10⭐ Telegram Stars за канал на месяц

Команды:
/menu — открыть меню
/add <тип> <id|url> [название] — добавить источник
/remove <id> — удалить источник
/sources — список источников
/topic + <тема> — ✅ показывать только такие (белый список)
/topic - <тема> — 🚫 скрывать такие (чёрный список)
/topic del <тема> — удалить тему из фильтров
/topic include <тема> / /topic exclude <тема>
/topics — список фильтров
/topic clear — сбросить все темы
/topic clear include|exclude — сбросить один список
/news [дни] — выжимка за N дней (по умолчанию 3, макс. 30)
/reset — служебный сброс служебных меток
/cancel — отменить ввод
/help — эта справка

Если задан белый список (✅), в выжимку попадают только совпадения.
Чёрный список (🚫) всегда отсекает совпадения. Без фильтров — все посты
(кроме стоп-слов/рекламы).

Типы источников:
• telegram — публичный канал (@channel)
• ria — лента РИА (main, politics, world, …) или URL RSS
• rss — любой RSS/Atom URL
• facebook — страница (нужен RSSHUB_BASE_URL) или URL RSS
• twitter — аккаунт X/Twitter (нужен RSSHUB_BASE_URL) или URL RSS

Примеры:
/add telegram bbcnews
/add ria main
/topic + seo
/topic - крипта
/news
/news 5
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    if update.effective_user:
        db.ensure_user(update.effective_user.id)
    if update.message:
        await update.message.reply_text(
            "Привет! Я собираю выжимку постов из ваших каналов в одну ленту — "
            "читаете портянку здесь, в оригинал переходите по ссылке.",
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
    settings: Settings = context.application.bot_data["settings"]
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
        ensure_can_add_source(db, settings, user_id)
        source = db.add_source(user_id, source_type, identifier, title)
    except SourceLimitError as exc:
        await update.message.reply_text(str(exc))
        await send_slot_invoice(
            update,
            context,
            pending_source=dump_pending_source(source_type, identifier, title),
        )
        return
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    await update.message.reply_text(
        f"Добавлен источник #{source.id}: [{source.source_type}] {source.title}\n"
        f"`{source.identifier}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_reply_keyboard(),
    )


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if not query:
        return
    settings: Settings = context.application.bot_data["settings"]
    ok = (
        query.currency == "XTR"
        and query.total_amount == settings.stars_per_extra_source
        and query.invoice_payload in {PAYLOAD_BUY_SLOT, PAYLOAD_BUY_SLOT_ADD}
    )
    if ok:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Некорректный платёж. Попробуйте снова.")


async def successful_payment_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not update.effective_user or not update.message.successful_payment:
        return
    payment = update.message.successful_payment
    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    user_id = update.effective_user.id

    if payment.currency != "XTR":
        await update.message.reply_text("Неожиданная валюта платежа.")
        return
    if payment.total_amount != settings.stars_per_extra_source:
        await update.message.reply_text("Сумма платежа не совпала. Напишите в поддержку.")
        return

    _, expires = db.add_paid_slot(
        user_id,
        stars_paid=payment.total_amount,
        days=settings.paid_slot_days,
        telegram_payment_charge_id=payment.telegram_payment_charge_id,
    )

    note = (
        f"Оплата прошла: +1 слот на {settings.paid_slot_days} дн. "
        f"(до {expires.strftime('%d.%m.%Y')})."
    )

    pending = None
    if payment.invoice_payload == PAYLOAD_BUY_SLOT_ADD:
        pending = parse_pending_source(context.user_data.pop("pending_source", None))

    if pending:
        source_type, identifier, title = pending
        try:
            ensure_can_add_source(db, settings, user_id)
            source = db.add_source(user_id, source_type, identifier, title)
            await update.message.reply_text(
                f"{note}\nДобавлен источник #{source.id}: "
                f"[{source.source_type}] {source.title}",
                reply_markup=_sources_markup(db, settings, user_id),
            )
            return
        except (SourceLimitError, ValueError) as exc:
            await update.message.reply_text(
                f"{note}\nНе удалось сразу добавить источник: {exc}\n"
                f"Слот уже активен — повторите /add.",
                reply_markup=_sources_markup(db, settings, user_id),
            )
            return

    await update.message.reply_text(
        note + "\nТеперь можно добавить ещё один источник.",
        reply_markup=_sources_markup(db, settings, user_id),
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

    def _status() -> str:
        return topics_text(db, user_id)

    try:
        if action in {"add", "a", "+", "include", "in", "pos", "show"}:
            topics = parse_topic_args(rest)
            added: list[str] = []
            for topic in topics:
                try:
                    db.add_topic(user_id, topic, kind="include")
                    added.append(topic)
                except ValueError:
                    pass
            if not added:
                await update.message.reply_text("Все указанные темы уже в ✅ списке.")
                return
            await update.message.reply_text(
                "✅ Добавлены (показывать): " + ", ".join(added) + "\n\n" + _status()
            )
            return

        if action in {"exclude", "ex", "ban", "hide", "neg", "block", "-"}:
            topics = parse_topic_args(rest)
            added = []
            for topic in topics:
                try:
                    db.add_topic(user_id, topic, kind="exclude")
                    added.append(topic)
                except ValueError:
                    pass
            if not added:
                await update.message.reply_text("Все указанные темы уже в 🚫 списке.")
                return
            await update.message.reply_text(
                "🚫 Добавлены (скрывать): " + ", ".join(added) + "\n\n" + _status()
            )
            return

        if action in {"del", "delete", "remove", "rm"}:
            topics = parse_topic_args(rest)
            removed = [t for t in topics if db.remove_topic(user_id, t)]
            if not removed:
                await update.message.reply_text("Таких тем нет.")
                return
            await update.message.reply_text(
                "Удалены: " + ", ".join(removed) + "\n\n" + _status()
            )
            return

        if action in {"list", "ls"}:
            await show_topics_panel(update, context)
            return

        if action in {"clear", "reset", "all"}:
            kind = None
            if rest:
                raw = rest[0].lower()
                if raw in {"include", "+", "pos", "show"}:
                    kind = "include"
                elif raw in {"exclude", "-", "neg", "hide", "ban"}:
                    kind = "exclude"
            count = db.clear_topics(user_id, kind=kind)
            label = {
                "include": "из ✅ списка",
                "exclude": "из 🚫 списка",
            }.get(kind or "", "")
            await update.message.reply_text(
                f"Сброшено тем {label}: {count}.\n\n" + _status()
            )
            return

        topics = parse_topic_args(args)
        added = []
        for topic in topics:
            try:
                db.add_topic(user_id, topic, kind="include")
                added.append(topic)
            except ValueError:
                pass
        if not added:
            await update.message.reply_text("Все указанные темы уже в ✅ списке.")
            return
        await update.message.reply_text(
            "✅ Добавлены (показывать): " + ", ".join(added) + "\n\n" + _status()
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))


async def topics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    await show_topics_panel(update, context)


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        days = parse_days_arg(list(context.args or []))
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await send_digest_to_chat(update, context, days=days)


async def reset_cursor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    db.reset_last_digest_at(update.effective_user.id)
    await update.message.reply_text(
        "Служебные метки сброшены. Период выжимки задаётся через "
        "/news [дни] (по умолчанию 3).",
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


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("cancel", cancel_awaiting))
    app.add_handler(CommandHandler("add", add_source))
    app.add_handler(CommandHandler("remove", remove_source))
    app.add_handler(CommandHandler("sources", list_sources))
    app.add_handler(CommandHandler("topic", topic_cmd))
    app.add_handler(CommandHandler("topics", topics_cmd))
    app.add_handler(CommandHandler("filter", topic_cmd))
    app.add_handler(CommandHandler("filters", topics_cmd))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("digest", news))
    app.add_handler(CommandHandler("reset", reset_cursor))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler)
    )
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^m:"))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_router)
    )
