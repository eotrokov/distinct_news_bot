from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.billing import (
    SourceLimitError,
    dump_pending_source,
    ensure_can_add_source,
    send_slot_invoice,
    sources_quota_text,
)
from bot.config import Settings
from bot.db import Database
from bot.digest import DigestService, parse_add_args
from bot.fetchers.ria import RIA_FEEDS
from bot.fetchers.telegram import normalize_telegram_handle
from bot.keyboards import (
    BTN_HELP,
    BTN_MENU,
    BTN_NEWS,
    BTN_RESET,
    BTN_SOURCES,
    BTN_TOPICS,
    REPLY_BUTTONS,
    SOURCE_PROMPTS,
    back_home_keyboard,
    digest_page_keyboard,
    main_inline_keyboard,
    main_reply_keyboard,
    source_type_keyboard,
    sources_keyboard,
    topics_keyboard,
)
from bot.topics import parse_topic_args

logger = logging.getLogger(__name__)

AWAITING_KEY = "awaiting"
DIGEST_SESSIONS_KEY = "digest_sessions"

MENU_TEXT = (
    "Выжимка постов за последние дни — одна лента вместо обхода каналов.\n"
    "По умолчанию 3 дня; команда /news 5 — за 5 дней.\n"
    "Если новостей больше 10 — листайте стрелками.\n"
    "Снизу — быстрые кнопки, здесь — подробное меню."
)


def clear_awaiting(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(AWAITING_KEY, None)


def set_awaiting(context: ContextTypes.DEFAULT_TYPE, payload: dict) -> None:
    context.user_data[AWAITING_KEY] = payload


def get_awaiting(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    value = context.user_data.get(AWAITING_KEY)
    return value if isinstance(value, dict) else None


def _store_digest_pages(
    context: ContextTypes.DEFAULT_TYPE, user_id: int, pages: list[str]
) -> None:
    sessions = context.application.bot_data.setdefault(DIGEST_SESSIONS_KEY, {})
    sessions[user_id] = {"pages": pages, "page": 0}


def _get_digest_pages(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> list[str] | None:
    sessions = context.application.bot_data.get(DIGEST_SESSIONS_KEY) or {}
    session = sessions.get(user_id)
    if not isinstance(session, dict):
        return None
    pages = session.get("pages")
    return pages if isinstance(pages, list) and pages else None


async def show_main_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit: bool = False,
) -> None:
    clear_awaiting(context)
    text = MENU_TEXT
    markup = main_inline_keyboard()
    if edit and update.callback_query and update.callback_query.message:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
        return
    if update.effective_message:
        await update.effective_message.reply_text(
            "Быстрые кнопки внизу экрана.",
            reply_markup=main_reply_keyboard(),
        )
        await update.effective_message.reply_text(text, reply_markup=markup)


async def send_digest_to_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    days: int | None = None,
) -> None:
    if not update.effective_user or not update.effective_message:
        return
    digest: DigestService = context.application.bot_data["digest"]
    user_id = update.effective_user.id
    status = await update.effective_message.reply_text("Собираю выжимку…")
    try:
        items, errors, topics, days_used, analysis = await digest.collect_for_user(
            user_id, days=days
        )
    except Exception:  # noqa: BLE001
        logger.exception("Digest failed for user %s", user_id)
        await status.edit_text("Не удалось собрать выжимку. Попробуйте позже.")
        return

    pages = digest.format_digest(
        analysis,
        days_used,
        errors=errors,
        topics=topics,
    )
    _store_digest_pages(context, user_id, pages)
    digest.mark_digest_delivered(user_id, items)

    markup = (
        digest_page_keyboard(0, len(pages))
        if len(pages) > 1
        else back_home_keyboard()
    )
    await status.edit_text(
        pages[0],
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=markup,
    )


def _sources_markup(db: Database, settings: Settings, user_id: int):
    current = db.count_sources(user_id)
    limit = db.source_limit(user_id, settings.free_source_limit)
    return sources_keyboard(
        db.list_sources(user_id),
        show_buy_slot=current >= limit,
        stars=settings.stars_per_extra_source,
    )


def sources_text(db: Database, settings: Settings, user_id: int) -> str:
    sources = db.list_sources(user_id)
    quota = sources_quota_text(db, settings, user_id)
    if not sources:
        return (
            "Источников пока нет.\n"
            f"{quota}\n"
            "Нажмите «Добавить источник» или используйте /add"
        )
    lines = [quota, "", "Ваши источники (нажмите, чтобы удалить):"]
    active, paused = db.list_active_sources(user_id, settings.free_source_limit)
    active_ids = {s.id for s in active}
    for s in sources:
        mark = "" if s.id in active_ids else " ⏸"
        lines.append(f"#{s.id} [{s.source_type}] {s.title}{mark}\n  {s.identifier}")
    if paused:
        lines.append("\n⏸ — на паузе, пока нет оплаченного слота.")
    return "\n".join(lines)


def topics_text(db: Database, user_id: int) -> str:
    rows = db.list_topic_rows(user_id)
    if not rows:
        return (
            "Темы не заданы — сводка без фильтра.\n"
            "Нажмите «Добавить тему» или /topic add seo"
        )
    lines = ["Активные темы (OR-фильтр). Нажмите тему, чтобы удалить:"]
    for _, topic in rows:
        lines.append(f"• {topic}")
    return "\n".join(lines)


async def show_sources_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit: bool = False,
) -> None:
    clear_awaiting(context)
    if not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    user_id = update.effective_user.id
    text = sources_text(db, settings, user_id)
    markup = _sources_markup(db, settings, user_id)
    if edit and update.callback_query and update.callback_query.message:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def show_topics_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit: bool = False,
) -> None:
    clear_awaiting(context)
    if not update.effective_user:
        return
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id
    text = topics_text(db, user_id)
    markup = topics_keyboard(db.list_topic_rows(user_id))
    if edit and update.callback_query and update.callback_query.message:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    data = query.data or ""
    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    user_id = update.effective_user.id
    db.ensure_user(user_id)

    if data == "m:dg:noop":
        await query.answer()
        return

    if data.startswith("m:dg:"):
        await query.answer()
        try:
            page = int(data.split(":")[2])
        except (IndexError, ValueError):
            return
        pages = _get_digest_pages(context, user_id)
        if not pages:
            await query.answer(
                "Выжимка устарела — нажмите «Выжимка» ещё раз.",
                show_alert=True,
            )
            return
        page = max(0, min(page, len(pages) - 1))
        sessions = context.application.bot_data.get(DIGEST_SESSIONS_KEY) or {}
        if user_id in sessions:
            sessions[user_id]["page"] = page
        try:
            await query.edit_message_text(
                pages[page],
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=digest_page_keyboard(page, len(pages)),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to paginate digest for user %s", user_id)
        return

    await query.answer()

    if data == "m:home":
        await show_main_menu(update, context, edit=True)
        return
    if data == "m:news":
        clear_awaiting(context)
        await send_digest_to_chat(update, context)
        return
    if data == "m:sources":
        await show_sources_panel(update, context, edit=True)
        return
    if data == "m:topics":
        await show_topics_panel(update, context, edit=True)
        return
    if data == "m:help":
        clear_awaiting(context)
        from bot.handlers import HELP_TEXT

        await query.edit_message_text(HELP_TEXT, reply_markup=back_home_keyboard())
        return
    if data == "m:reset":
        clear_awaiting(context)
        db.reset_last_digest_at(user_id)
        await query.edit_message_text(
            "Служебные метки сброшены. Период задаётся через /news [дни] (по умолчанию 3).",
            reply_markup=back_home_keyboard(),
        )
        return
    if data == "m:buy_slot":
        clear_awaiting(context)
        await send_slot_invoice(update, context)
        return
    if data == "m:src_add":
        clear_awaiting(context)
        try:
            ensure_can_add_source(db, settings, user_id)
        except SourceLimitError as exc:
            await query.edit_message_text(
                f"{exc}\n\nОплатите слот Stars, затем добавьте канал.",
                reply_markup=_sources_markup(db, settings, user_id),
            )
            await send_slot_invoice(update, context)
            return
        await query.edit_message_text(
            "Выберите тип источника:",
            reply_markup=source_type_keyboard(),
        )
        return
    if data.startswith("m:src_type:"):
        source_type = data.split(":", 2)[2]
        if source_type not in SOURCE_PROMPTS:
            await query.answer("Неизвестный тип", show_alert=True)
            return
        set_awaiting(context, {"kind": "source", "type": source_type})
        prompt = SOURCE_PROMPTS[source_type]
        await query.edit_message_text(
            f"{prompt}\n\nИли /cancel чтобы отменить.",
            reply_markup=back_home_keyboard(),
        )
        return
    if data.startswith("m:src_del:"):
        source_id = int(data.split(":")[2])
        ok = db.remove_source(user_id, source_id)
        note = f"Источник #{source_id} удалён.\n\n" if ok else "Источник не найден.\n\n"
        text = note + sources_text(db, settings, user_id)
        await query.edit_message_text(
            text, reply_markup=_sources_markup(db, settings, user_id)
        )
        return
    if data == "m:topic_add":
        set_awaiting(context, {"kind": "topic"})
        await query.edit_message_text(
            "Пришлите тему или несколько через запятую/пробел.\n"
            "Пример: seo\nПример: marketing ai\n\n/cancel — отмена.",
            reply_markup=back_home_keyboard(),
        )
        return
    if data.startswith("m:topic_del:"):
        topic_id = int(data.split(":")[2])
        removed = db.remove_topic_by_id(user_id, topic_id)
        note = (
            f"Тема «{removed}» удалена.\n\n"
            if removed
            else "Тема не найдена.\n\n"
        )
        text = note + topics_text(db, user_id)
        await query.edit_message_text(
            text, reply_markup=topics_keyboard(db.list_topic_rows(user_id))
        )
        return
    if data == "m:topic_clear":
        count = db.clear_topics(user_id)
        await query.edit_message_text(
            f"Сброшено тем: {count}.\n\n" + topics_text(db, user_id),
            reply_markup=topics_keyboard(db.list_topic_rows(user_id)),
        )
        return


async def on_reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.message.text:
        return
    text = update.message.text.strip()
    if text not in REPLY_BUTTONS:
        return

    clear_awaiting(context)
    db: Database = context.application.bot_data["db"]
    db.ensure_user(update.effective_user.id)

    if text == BTN_NEWS:
        await send_digest_to_chat(update, context)
    elif text == BTN_SOURCES:
        await show_sources_panel(update, context)
    elif text == BTN_TOPICS:
        await show_topics_panel(update, context)
    elif text == BTN_MENU:
        await show_main_menu(update, context)
    elif text == BTN_HELP:
        from bot.handlers import HELP_TEXT

        await update.message.reply_text(HELP_TEXT, reply_markup=main_reply_keyboard())
    elif text == BTN_RESET:
        db.reset_last_digest_at(update.effective_user.id)
        await update.message.reply_text(
            "Служебные метки сброшены. Период задаётся через /news [дни] (по умолчанию 3).",
            reply_markup=main_reply_keyboard(),
        )


async def on_awaiting_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.message.text:
        return
    text = update.message.text.strip()
    if text in REPLY_BUTTONS:
        return
    if text.startswith("/"):
        return

    awaiting = get_awaiting(context)
    if not awaiting:
        return

    db: Database = context.application.bot_data["db"]
    settings: Settings = context.application.bot_data["settings"]
    user_id = update.effective_user.id
    kind = awaiting.get("kind")

    try:
        if kind == "source":
            source_type = str(awaiting.get("type"))
            try:
                ensure_can_add_source(db, settings, user_id)
                source = _add_source_from_text(db, user_id, source_type, text)
            except SourceLimitError as exc:
                pending = _pending_from_text(source_type, text)
                clear_awaiting(context)
                await update.message.reply_text(str(exc))
                await send_slot_invoice(update, context, pending_source=pending)
                return
            clear_awaiting(context)
            await update.message.reply_text(
                f"Добавлен источник #{source.id}: [{source.source_type}] {source.title}\n"
                f"{source.identifier}",
                reply_markup=_sources_markup(db, settings, user_id),
            )
            return

        if kind == "topic":
            topics = parse_topic_args(text.split())
            added: list[str] = []
            for topic in topics:
                try:
                    db.add_topic(user_id, topic)
                    added.append(topic)
                except ValueError:
                    pass
            clear_awaiting(context)
            if not added:
                await update.message.reply_text(
                    "Все указанные темы уже были добавлены.",
                    reply_markup=topics_keyboard(db.list_topic_rows(user_id)),
                )
                return
            await update.message.reply_text(
                "Добавлены темы: "
                + ", ".join(added)
                + "\n\n"
                + topics_text(db, user_id),
                reply_markup=topics_keyboard(db.list_topic_rows(user_id)),
            )
            return
    except ValueError as exc:
        await update.message.reply_text(f"{exc}\nПопробуйте ещё раз или /cancel")


def _normalize_source_args(
    source_type: str, identifier: str, title: str, raw: str | None = None
) -> tuple[str, str, str]:
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
    if raw and source_type in {"rss", "facebook", "twitter"} and (
        raw.startswith("http://") or raw.startswith("https://")
    ):
        identifier = raw.strip()
        title = title if title and not title.startswith("http") else identifier[:60]
    return source_type, identifier, title


def _pending_from_text(source_type: str, raw: str) -> dict[str, str]:
    source_type, identifier, title = parse_add_args([source_type, *raw.split()])
    source_type, identifier, title = _normalize_source_args(
        source_type, identifier, title, raw=raw
    )
    return dump_pending_source(source_type, identifier, title)


def _add_source_from_text(
    db: Database, user_id: int, source_type: str, raw: str
):
    source_type, identifier, title = parse_add_args([source_type, *raw.split()])
    source_type, identifier, title = _normalize_source_args(
        source_type, identifier, title, raw=raw
    )
    return db.add_source(user_id, source_type, identifier, title)


async def cancel_awaiting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_awaiting(context)
    if update.message:
        await update.message.reply_text(
            "Отменено.",
            reply_markup=main_reply_keyboard(),
        )
        await show_main_menu(update, context)
