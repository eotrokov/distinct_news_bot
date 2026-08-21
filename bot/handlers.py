from __future__ import annotations

import logging
import re

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
from bot.channels import add_channels_bulk, format_bulk_add_result, parse_channel_list
from bot.config import Settings
from bot.db import Database
from bot.digest import parse_days_arg
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
    sources_text,
    topics_text,
)
from bot.topics import parse_topic_args

logger = logging.getLogger(__name__)

HELP_TEXT = """\
Distinct News — SEO-дайджест из ваших Telegram-каналов.

Бот собирает посты за выбранный период, убирает рекламу и дубли,
делает подробную выжимку (несколько предложений на новость) и
отдаёт одну ленту. Если пунктов больше 10 — листайте ◀ ▶.

Лимиты:
• до 20 каналов бесплатно
• дальше — 10⭐ за канал на 30 дней

Команды:
/news [дни] — выжимка (по умолчанию 3 дня, макс. 30)
/weekly — главные за 7 дней по реакциям
/weekly on|off — авто-рассылка топа раз в неделю
/add @a @b @c — добавить каналы пачкой
/sources — список каналов
/remove <id> — удалить канал

Фильтры тем:
/topic + seo — ✅ показывать
/topic - крипта — 🚫 скрывать
/topics — оба списка

/menu — меню · /cancel — отмена · /help — справка

Примеры:
/add @searchengines @seonews
/topic + алгоритм
/news 5
/weekly
"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    if update.effective_user:
        db.ensure_user(update.effective_user.id)
    if update.message:
        await update.message.reply_text(
            "Привет! Соберу SEO-выжимку из ваших Telegram-каналов: "
            "можно добавлять каналы пачкой, выжимка подробная, "
            "раз в неделю — топ по реакциям.\n"
            "Нажмите «Выжимка» или /news — справка: /help",
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
    text = update.message.text or ""
    # Prefer full message body so multi-line pastes work (/add @a\n@b).
    match = re.match(r"(?is)^\s*/add(?:@\w+)?(?:\s+|$)(.*)$", text, re.DOTALL)
    raw = (match.group(1) if match else " ".join(context.args or [])).strip()
    try:
        handles = parse_channel_list(raw)
        result = add_channels_bulk(db, settings, user_id, handles)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    await update.message.reply_text(
        format_bulk_add_result(result),
        reply_markup=main_reply_keyboard(),
    )
    blocked = list(result.get("blocked_by_limit") or [])
    if blocked:
        await send_slot_invoice(
            update,
            context,
            pending_source=dump_pending_source(
                "telegram", blocked[0], f"@{blocked[0]}"
            ),
        )


async def weekly_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id
    args = list(context.args or [])
    if args:
        action = args[0].lower()
        if action in {"on", "1", "enable", "вкл"}:
            db.set_weekly_digest_enabled(user_id, True)
            await update.message.reply_text(
                "Авто-топ недели включён (раз в 7 дней по реакциям)."
            )
            return
        if action in {"off", "0", "disable", "выкл"}:
            db.set_weekly_digest_enabled(user_id, False)
            await update.message.reply_text("Авто-топ недели выключен.")
            return
        if action in {"status", "статус"}:
            enabled = db.is_weekly_digest_enabled(user_id)
            await update.message.reply_text(
                "Авто-топ недели: " + ("включён" if enabled else "выключен")
            )
            return
    await send_digest_to_chat(update, context, days=7, mode="weekly")


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
                f"{note}\nДобавлен канал #{source.id}: {source.title}",
                reply_markup=_sources_markup(db, settings, user_id),
            )
            return
        except (SourceLimitError, ValueError) as exc:
            await update.message.reply_text(
                f"{note}\nНе удалось сразу добавить канал: {exc}\n"
                f"Слот уже активен — повторите /add @channel.",
                reply_markup=_sources_markup(db, settings, user_id),
            )
            return

    await update.message.reply_text(
        note + "\nТеперь можно добавить ещё один канал.",
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
        "Служебные метки сброшены. На период выжимки это не влияет — "
        "задайте его через /news [дни] (по умолчанию 3).",
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
    app.add_handler(CommandHandler("weekly", weekly_cmd))
    app.add_handler(CommandHandler("reset", reset_cursor))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler)
    )
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^m:"))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_router)
    )
