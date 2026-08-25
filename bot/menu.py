from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.db import Database
from bot.digest import DigestService, parse_add_args
from bot.keyboards import (
    BTN_HELP,
    BTN_MENU,
    BTN_NEW_ONLY,
    BTN_NEWS,
    BTN_SCHEDULE,
    BTN_SOURCES,
    BTN_TOPICS,
    REPLY_BUTTONS,
    TELEGRAM_SOURCE_PROMPT,
    back_home_keyboard,
    digest_mode_keyboard,
    digest_page_keyboard,
    main_inline_keyboard,
    main_reply_keyboard,
    schedule_keyboard,
    sources_keyboard,
    topics_keyboard,
)
from bot.schedule import format_schedule_status
from bot.topics import parse_topic_args

logger = logging.getLogger(__name__)

AWAITING_KEY = "awaiting"
DIGEST_SESSIONS_KEY = "digest_sessions"

MENU_TEXT = (
    "Управление ботом кнопками.\n"
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
    *,
    only_unseen: bool = False,
) -> None:
    if not update.effective_user or not update.effective_message:
        return
    digest: DigestService = context.application.bot_data["digest"]
    user_id = update.effective_user.id
    status_text = (
        "Собираю только новое…"
        if only_unseen
        else "Собираю сводку по реакциям…"
    )
    status = await update.effective_message.reply_text(status_text)
    try:
        items, errors, topics, days_used, analysis = await digest.collect_for_user(
            user_id, days=days, only_unseen=only_unseen
        )
    except Exception:  # noqa: BLE001
        logger.exception("Digest failed for user %s", user_id)
        await status.edit_text("Не удалось собрать сводку. Попробуйте позже.")
        return

    pages = digest.format_digest(
        analysis, days_used, errors=errors, topics=topics
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


def sources_text(db: Database, user_id: int) -> str:
    sources = db.list_sources(user_id)
    if not sources:
        return (
            "Каналов пока нет.\n"
            "Нажмите «Добавить канал» или пришлите @channel"
        )
    lines = ["Ваши каналы (нажмите, чтобы удалить):"]
    for s in sources:
        lines.append(f"#{s.id} {s.title}\n  {s.identifier}")
        if s.source_type != "telegram":
            lines[-1] += f"\n  ⚠ устаревший тип [{s.source_type}] — удалите"
    return "\n".join(lines)


def topics_text(db: Database, user_id: int) -> str:
    rows = db.list_topic_rows(user_id)
    if not rows:
        return (
            "Темы не заданы — сводка без фильтра.\n"
            "Нажмите «Добавить тему» или /topic add ai"
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
    user_id = update.effective_user.id
    text = sources_text(db, user_id)
    markup = sources_keyboard(db.list_sources(user_id))
    if edit and update.callback_query and update.callback_query.message:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def show_schedule_panel(
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
    schedule = db.get_schedule(user_id)
    text = format_schedule_status(schedule)
    markup = schedule_keyboard(enabled=schedule.enabled)
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
    user_id = update.effective_user.id
    db.ensure_user(user_id)

    if data == "m:dg:noop":
        await query.answer()
        return

    if data.startswith("m:dg:"):
        try:
            page = int(data.split(":")[2])
        except (IndexError, ValueError):
            await query.answer()
            return
        pages = _get_digest_pages(context, user_id)
        if not pages:
            await query.answer(
                "Сводка устарела — нажмите «Сводка» ещё раз.",
                show_alert=True,
            )
            return
        await query.answer()
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
        await query.edit_message_text(
            "Какую сводку показать?",
            reply_markup=digest_mode_keyboard(),
        )
        return
    if data == "m:news:top":
        clear_awaiting(context)
        await send_digest_to_chat(update, context, only_unseen=False)
        return
    if data == "m:news:new":
        clear_awaiting(context)
        await send_digest_to_chat(update, context, only_unseen=True)
        return
    if data == "m:sources":
        await show_sources_panel(update, context, edit=True)
        return
    if data == "m:topics":
        await show_topics_panel(update, context, edit=True)
        return
    if data == "m:schedule":
        await show_schedule_panel(update, context, edit=True)
        return
    if data == "m:sched:on":
        schedule = db.set_schedule(user_id, enabled=True)
        await query.edit_message_text(
            format_schedule_status(schedule),
            reply_markup=schedule_keyboard(enabled=schedule.enabled),
        )
        return
    if data == "m:sched:off":
        schedule = db.set_schedule(user_id, enabled=False)
        await query.edit_message_text(
            format_schedule_status(schedule),
            reply_markup=schedule_keyboard(enabled=schedule.enabled),
        )
        return
    if data.startswith("m:sched:h:"):
        hour = int(data.split(":")[3])
        schedule = db.set_schedule(user_id, enabled=True, hour=hour)
        await query.edit_message_text(
            format_schedule_status(schedule),
            reply_markup=schedule_keyboard(enabled=schedule.enabled),
        )
        return
    if data.startswith("m:sched:tz:"):
        offset = int(data.split(":")[3])
        schedule = db.set_schedule(user_id, tz_offset_minutes=offset)
        await query.edit_message_text(
            format_schedule_status(schedule),
            reply_markup=schedule_keyboard(enabled=schedule.enabled),
        )
        return
    if data == "m:help":
        clear_awaiting(context)
        from bot.handlers import HELP_TEXT

        await query.edit_message_text(HELP_TEXT, reply_markup=back_home_keyboard())
        return
    if data == "m:reset":
        # Legacy callback: clear seen items so "Только новое" can show them again.
        clear_awaiting(context)
        cleared = db.clear_seen(user_id)
        db.reset_last_digest_at(user_id)
        await query.edit_message_text(
            f"Просмотренное сброшено ({cleared}). "
            "«Только новое» снова покажет эти посты.",
            reply_markup=back_home_keyboard(),
        )
        return
    if data == "m:src_add" or data.startswith("m:src_type:"):
        # Legacy m:src_type:* callbacks still open the Telegram add flow.
        clear_awaiting(context)
        set_awaiting(context, {"kind": "source", "type": "telegram"})
        await query.edit_message_text(
            f"{TELEGRAM_SOURCE_PROMPT}\n\nИли /cancel чтобы отменить.",
            reply_markup=back_home_keyboard(),
        )
        return
    if data.startswith("m:src_del:"):
        source_id = int(data.split(":")[2])
        ok = db.remove_source(user_id, source_id)
        note = f"Источник #{source_id} удалён.\n\n" if ok else "Источник не найден.\n\n"
        text = note + sources_text(db, user_id)
        await query.edit_message_text(
            text, reply_markup=sources_keyboard(db.list_sources(user_id))
        )
        return
    if data == "m:topic_add":
        set_awaiting(context, {"kind": "topic"})
        await query.edit_message_text(
            "Пришлите тему или несколько через запятую/пробел.\n"
            "Пример: ai\nПример: marketing finance\n\n/cancel — отмена.",
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

    # Reply buttons cancel any pending input.
    clear_awaiting(context)
    db: Database = context.application.bot_data["db"]
    db.ensure_user(update.effective_user.id)

    if text == BTN_NEWS:
        await send_digest_to_chat(update, context, only_unseen=False)
    elif text == BTN_NEW_ONLY:
        await send_digest_to_chat(update, context, only_unseen=True)
    elif text == BTN_SOURCES:
        await show_sources_panel(update, context)
    elif text == BTN_TOPICS:
        await show_topics_panel(update, context)
    elif text == BTN_SCHEDULE:
        await show_schedule_panel(update, context)
    elif text == BTN_MENU:
        await show_main_menu(update, context)
    elif text == BTN_HELP:
        from bot.handlers import HELP_TEXT

        await update.message.reply_text(HELP_TEXT, reply_markup=main_reply_keyboard())


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
    user_id = update.effective_user.id
    kind = awaiting.get("kind")

    try:
        if kind == "onboard":
            from bot.addlist import extract_addlist_slug, parse_telegram_handles
            from bot.handlers import begin_addlist_import
            from bot.sources_ops import add_telegram_from_text, format_add_report

            if extract_addlist_slug(text) and "addlist" in text.lower():
                clear_awaiting(context)
                await begin_addlist_import(update, context, text)
                return

            handles = parse_telegram_handles(text)
            if not handles:
                await update.message.reply_text(
                    "Не нашёл каналов. Пришлите @name или https://t.me/name\n"
                    "Или /cancel чтобы отменить.",
                    reply_markup=main_reply_keyboard(),
                )
                return

            added, skipped = add_telegram_from_text(db, user_id, text)
            clear_awaiting(context)
            await update.message.reply_text(
                format_add_report(folder_title=None, added=added, skipped=skipped),
                reply_markup=main_reply_keyboard(),
            )
            if added or db.list_sources(user_id):
                await update.message.reply_text(
                    "Отлично! Собираю пробную сводку…"
                )
                await send_digest_to_chat(update, context, only_unseen=False)
            return

        if kind == "addlist_channels":
            from bot.sources_ops import add_telegram_from_text, format_add_report

            folder_title = str(awaiting.get("folder_title") or "")
            added, skipped = add_telegram_from_text(db, user_id, text)
            clear_awaiting(context)
            await update.message.reply_text(
                format_add_report(
                    folder_title=folder_title or None,
                    added=added,
                    skipped=skipped,
                ),
                reply_markup=sources_keyboard(db.list_sources(user_id)),
            )
            return

        if kind == "source":
            from bot.addlist import extract_addlist_slug, parse_telegram_handles
            from bot.handlers import begin_addlist_import
            from bot.sources_ops import (
                add_single_source,
                add_telegram_from_text,
                format_add_report,
            )

            if extract_addlist_slug(text) and "addlist" in text.lower():
                clear_awaiting(context)
                await begin_addlist_import(update, context, text)
                return

            handles = parse_telegram_handles(text)
            if len(handles) > 1:
                added, skipped = add_telegram_from_text(db, user_id, text)
                clear_awaiting(context)
                await update.message.reply_text(
                    format_add_report(
                        folder_title=None, added=added, skipped=skipped
                    ),
                    reply_markup=sources_keyboard(db.list_sources(user_id)),
                )
                return

            source_type, identifier, title = parse_add_args(
                ["telegram", *text.split()]
            )
            source = add_single_source(db, user_id, source_type, identifier, title)
            clear_awaiting(context)
            await update.message.reply_text(
                f"Добавлен канал #{source.id}: {source.title}\n"
                f"{source.identifier}",
                reply_markup=sources_keyboard(db.list_sources(user_id)),
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


async def cancel_awaiting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_awaiting(context)
    if update.message:
        await update.message.reply_text(
            "Отменено.",
            reply_markup=main_reply_keyboard(),
        )
        await show_main_menu(update, context)
