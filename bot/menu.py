from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.channel_presets import CHANNEL_PRESETS, get_channel_preset
from bot.db import Database
from bot.digest import DigestService, parse_add_args
from bot.keyboards import (
    BTN_HELP,
    BTN_MENU,
    BTN_NEW_ONLY,
    BTN_NEWS,
    BTN_PLAN,
    BTN_SCHEDULE,
    BTN_SOURCES,
    BTN_TOPICS,
    REPLY_BUTTONS,
    TELEGRAM_SOURCE_PROMPT,
    back_home_keyboard,
    channel_presets_keyboard,
    digest_mode_keyboard,
    digest_page_keyboard,
    main_inline_keyboard,
    main_reply_keyboard,
    plan_keyboard,
    schedule_keyboard,
    sources_keyboard,
    topics_keyboard,
)
from bot.chat_scope import (
    group_buy_hint,
    group_manage_denied_text,
    is_private_chat,
    user_can_manage,
    workspace_id,
)
from bot.plans import format_plan_status
from bot.schedule import format_schedule_status
from bot.topics import parse_topic_args

logger = logging.getLogger(__name__)

AWAITING_KEY = "awaiting"
DIGEST_SESSIONS_KEY = "digest_sessions"


def _reply_kb(update: Update):
    """Reply keyboard only in private chats."""
    if is_private_chat(update.effective_chat):
        return main_reply_keyboard()
    return None


async def _require_manage(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, alert: bool = False
) -> bool:
    if await user_can_manage(update, context):
        return True
    msg = group_manage_denied_text()
    if alert and update.callback_query:
        await update.callback_query.answer(msg, show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text(msg)
    return False


def _ws(update: Update) -> int | None:
    return workspace_id(update)

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
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, pages: list[str]
) -> None:
    sessions = context.application.bot_data.setdefault(DIGEST_SESSIONS_KEY, {})
    sessions[chat_id] = {"pages": pages, "page": 0}


def _get_digest_pages(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int
) -> list[str] | None:
    sessions = context.application.bot_data.get(DIGEST_SESSIONS_KEY) or {}
    session = sessions.get(chat_id)
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
    if not is_private_chat(update.effective_chat):
        text = (
            "Меню для этого чата. Каналы и расписание общие для группы.\n"
            "Управлять настройками могут администраторы."
        )
    markup = main_inline_keyboard()
    if edit and update.callback_query and update.callback_query.message:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
        return
    if update.effective_message:
        if is_private_chat(update.effective_chat):
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
    chat_id = _ws(update)
    if chat_id is None:
        return
    digest: DigestService = context.application.bot_data["digest"]
    db: Database = context.application.bot_data["db"]
    db.ensure_user(chat_id)
    allowed, ent = db.consume_digest_quota(chat_id)
    if not allowed:
        limits = ent.limits()
        buy_hint = (
            "Оформите Pro: /buy pro"
            if is_private_chat(update.effective_chat)
            else group_buy_hint()
        )
        await update.effective_message.reply_text(
            f"Лимит сводок на сегодня ({limits.max_digests_per_day}).\n"
            f"{buy_hint}\nСтатус: /plan"
        )
        return
    status_text = (
        "Собираю только новое…"
        if only_unseen
        else "Собираю сводку по реакциям…"
    )
    status = await update.effective_message.reply_text(status_text)
    try:
        items, errors, topics, days_used, analysis = await digest.collect_for_user(
            chat_id, days=days, only_unseen=only_unseen
        )
    except Exception:  # noqa: BLE001
        logger.exception("Digest failed for chat %s", chat_id)
        await status.edit_text("Не удалось собрать сводку. Попробуйте позже.")
        return

    pages = digest.format_digest(
        analysis, days_used, errors=errors, topics=topics
    )
    _store_digest_pages(context, chat_id, pages)
    digest.mark_digest_delivered(chat_id, items)
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
            "Добавьте: /add @channel, кнопка «Добавить канал» "
            "или «Готовые наборы»"
        )
    lines = ["Каналы этого чата (нажмите, чтобы удалить):"]
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
    chat_id = _ws(update)
    if chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    db.ensure_user(chat_id)
    text = sources_text(db, chat_id)
    markup = sources_keyboard(db.list_sources(chat_id))
    if edit and update.callback_query and update.callback_query.message:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def show_channel_presets_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit: bool = False,
) -> None:
    clear_awaiting(context)
    lines = ["Готовые наборы каналов:"]
    for preset in CHANNEL_PRESETS:
        lines.append(
            f"• {preset.title} — {preset.description} "
            f"({preset.count} каналов)"
        )
        if preset.addlist_url:
            lines.append(f"  Папка: {preset.addlist_url}")
    text = "\n".join(lines)
    markup = channel_presets_keyboard()
    if edit and update.callback_query and update.callback_query.message:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def show_plan_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit: bool = False,
) -> None:
    clear_awaiting(context)
    chat_id = _ws(update)
    if chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    db.ensure_user(chat_id)
    ent = db.get_entitlement(chat_id)
    text = format_plan_status(ent)
    if not is_private_chat(update.effective_chat):
        text += "\n\n" + group_buy_hint()
        markup = back_home_keyboard()
    else:
        markup = plan_keyboard()
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
    chat_id = _ws(update)
    if chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    db.ensure_user(chat_id)
    ent = db.get_entitlement(chat_id)
    if not ent.limits().allow_schedule:
        text = (
            "Расписание доступно на Trial / Pro / Plus.\n"
            + (
                "Оформите подписку: /buy pro\n\n"
                if is_private_chat(update.effective_chat)
                else group_buy_hint() + "\n\n"
            )
            + format_plan_status(ent)
        )
        markup = (
            plan_keyboard()
            if is_private_chat(update.effective_chat)
            else back_home_keyboard()
        )
        if edit and update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(text, reply_markup=markup)
        elif update.effective_message:
            await update.effective_message.reply_text(text, reply_markup=markup)
        return
    schedule = db.get_schedule(chat_id)
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
    chat_id = _ws(update)
    if chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    db.ensure_user(chat_id)
    text = topics_text(db, chat_id)
    markup = topics_keyboard(db.list_topic_rows(chat_id))
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
    chat_id = _ws(update)
    if chat_id is None:
        await query.answer()
        return
    db.ensure_user(chat_id)

    if data == "m:dg:noop":
        await query.answer()
        return

    if data.startswith("m:dg:"):
        try:
            page = int(data.split(":")[2])
        except (IndexError, ValueError):
            await query.answer()
            return
        pages = _get_digest_pages(context, chat_id)
        if not pages:
            await query.answer(
                "Сводка устарела — нажмите «Сводка» ещё раз.",
                show_alert=True,
            )
            return
        await query.answer()
        page = max(0, min(page, len(pages) - 1))
        sessions = context.application.bot_data.get(DIGEST_SESSIONS_KEY) or {}
        if chat_id in sessions:
            sessions[chat_id]["page"] = page
        try:
            await query.edit_message_text(
                pages[page],
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=digest_page_keyboard(page, len(pages)),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to paginate digest for chat %s", chat_id)
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
    if data == "m:src_presets":
        await show_channel_presets_panel(update, context, edit=True)
        return
    if data.startswith("m:src_preset:"):
        if not await _require_manage(update, context, alert=True):
            return
        slug = data.removeprefix("m:src_preset:")
        preset = get_channel_preset(slug)
        if not preset:
            await query.answer("Набор не найден.", show_alert=True)
            return
        from bot.sources_ops import add_telegram_channels, format_add_report

        added, skipped = add_telegram_channels(db, chat_id, list(preset.channels))
        report = format_add_report(
            folder_title=preset.title,
            added=added,
            skipped=skipped,
        )
        if preset.addlist_url:
            report += f"\nПапка Telegram: {preset.addlist_url}"
        await query.edit_message_text(
            f"{report}\n\n{sources_text(db, chat_id)}",
            reply_markup=sources_keyboard(db.list_sources(chat_id)),
        )
        return
    if data == "m:topics":
        await show_topics_panel(update, context, edit=True)
        return
    if data == "m:schedule":
        await show_schedule_panel(update, context, edit=True)
        return
    if data == "m:plan":
        await show_plan_panel(update, context, edit=True)
        return
    if data.startswith("m:buy:"):
        if not is_private_chat(update.effective_chat):
            await query.answer(group_buy_hint(), show_alert=True)
            return
        plan = data.split(":")[2]
        from bot.payments import send_plan_invoice

        try:
            await send_plan_invoice(update, context, plan)
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
        return
    if data == "m:sched:on":
        if not await _require_manage(update, context, alert=True):
            return
        if not db.get_entitlement(chat_id).limits().allow_schedule:
            await query.answer("Расписание доступно на Pro", show_alert=True)
            return
        schedule = db.set_schedule(
            chat_id, enabled=True, hour=9, minute=55
        )
        await query.edit_message_text(
            format_schedule_status(schedule),
            reply_markup=schedule_keyboard(enabled=schedule.enabled),
        )
        return
    if data == "m:sched:off":
        if not await _require_manage(update, context, alert=True):
            return
        schedule = db.set_schedule(chat_id, enabled=False)
        await query.edit_message_text(
            format_schedule_status(schedule),
            reply_markup=schedule_keyboard(enabled=schedule.enabled),
        )
        return
    if data.startswith("m:sched:t:"):
        if not await _require_manage(update, context, alert=True):
            return
        if not db.get_entitlement(chat_id).limits().allow_schedule:
            await query.answer("Расписание доступно на Pro", show_alert=True)
            return
        parts = data.split(":")
        hour = int(parts[3])
        minute = int(parts[4]) if len(parts) > 4 else 0
        schedule = db.set_schedule(
            chat_id, enabled=True, hour=hour, minute=minute
        )
        await query.edit_message_text(
            format_schedule_status(schedule),
            reply_markup=schedule_keyboard(enabled=schedule.enabled),
        )
        return
    if data.startswith("m:sched:h:"):
        if not await _require_manage(update, context, alert=True):
            return
        if not db.get_entitlement(chat_id).limits().allow_schedule:
            await query.answer("Расписание доступно на Pro", show_alert=True)
            return
        hour = int(data.split(":")[3])
        schedule = db.set_schedule(
            chat_id, enabled=True, hour=hour, minute=0
        )
        await query.edit_message_text(
            format_schedule_status(schedule),
            reply_markup=schedule_keyboard(enabled=schedule.enabled),
        )
        return
    if data.startswith("m:sched:tz:"):
        if not await _require_manage(update, context, alert=True):
            return
        offset = int(data.split(":")[3])
        schedule = db.set_schedule(chat_id, tz_offset_minutes=offset)
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
        if not await _require_manage(update, context, alert=True):
            return
        clear_awaiting(context)
        cleared = db.clear_seen(chat_id)
        db.reset_last_digest_at(chat_id)
        await query.edit_message_text(
            f"Просмотренное сброшено ({cleared}). "
            "«Только новое» снова покажет эти посты.",
            reply_markup=back_home_keyboard(),
        )
        return
    if data == "m:src_add" or data.startswith("m:src_type:"):
        if not await _require_manage(update, context, alert=True):
            return
        clear_awaiting(context)
        set_awaiting(context, {"kind": "source", "type": "telegram"})
        prompt = (
            f"{TELEGRAM_SOURCE_PROMPT}\n\nИли /cancel чтобы отменить."
            if is_private_chat(update.effective_chat)
            else (
                "В группе удобнее командой:\n"
                "/add @channel\n"
                "Несколько: /add @ch1 @ch2\n\n/cancel — отмена."
            )
        )
        await query.edit_message_text(prompt, reply_markup=back_home_keyboard())
        return
    if data.startswith("m:src_del:"):
        if not await _require_manage(update, context, alert=True):
            return
        source_id = int(data.split(":")[2])
        ok = db.remove_source(chat_id, source_id)
        note = f"Источник #{source_id} удалён.\n\n" if ok else "Источник не найден.\n\n"
        text = note + sources_text(db, chat_id)
        await query.edit_message_text(
            text, reply_markup=sources_keyboard(db.list_sources(chat_id))
        )
        return
    if data == "m:topic_add":
        if not await _require_manage(update, context, alert=True):
            return
        set_awaiting(context, {"kind": "topic"})
        await query.edit_message_text(
            "Пришлите тему или несколько через запятую/пробел.\n"
            "В группе также: /topic add ai\n"
            "Пример: marketing finance\n\n/cancel — отмена.",
            reply_markup=back_home_keyboard(),
        )
        return
    if data.startswith("m:topic_del:"):
        if not await _require_manage(update, context, alert=True):
            return
        topic_id = int(data.split(":")[2])
        removed = db.remove_topic_by_id(chat_id, topic_id)
        note = (
            f"Тема «{removed}» удалена.\n\n"
            if removed
            else "Тема не найдена.\n\n"
        )
        text = note + topics_text(db, chat_id)
        await query.edit_message_text(
            text, reply_markup=topics_keyboard(db.list_topic_rows(chat_id))
        )
        return
    if data == "m:topic_clear":
        if not await _require_manage(update, context, alert=True):
            return
        count = db.clear_topics(chat_id)
        await query.edit_message_text(
            f"Сброшено тем: {count}.\n\n" + topics_text(db, chat_id),
            reply_markup=topics_keyboard(db.list_topic_rows(chat_id)),
        )
        return


async def on_reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.message.text:
        return
    # Reply keyboard is private-only; ignore stray presses in groups.
    if not is_private_chat(update.effective_chat):
        return
    text = update.message.text.strip()
    if text not in REPLY_BUTTONS:
        return

    clear_awaiting(context)
    chat_id = _ws(update)
    if chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    db.ensure_user(chat_id)

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
    elif text == BTN_PLAN:
        await show_plan_panel(update, context)
    elif text == BTN_MENU:
        await show_main_menu(update, context)
    elif text == BTN_HELP:
        from bot.handlers import HELP_TEXT

        await update.message.reply_text(HELP_TEXT, reply_markup=_reply_kb(update))


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

    chat_id = _ws(update)
    if chat_id is None:
        return
    if not await _require_manage(update, context):
        return

    db: Database = context.application.bot_data["db"]
    db.ensure_user(chat_id)
    kind = awaiting.get("kind")
    kb = _reply_kb(update)

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
                    reply_markup=kb,
                )
                return

            added, skipped = add_telegram_from_text(db, chat_id, text)
            clear_awaiting(context)
            await update.message.reply_text(
                format_add_report(folder_title=None, added=added, skipped=skipped),
                reply_markup=kb,
            )
            if added or db.list_sources(chat_id):
                await update.message.reply_text(
                    "Отлично! Собираю пробную сводку…"
                )
                await send_digest_to_chat(update, context, only_unseen=False)
            return

        if kind == "addlist_channels":
            from bot.sources_ops import add_telegram_from_text, format_add_report

            folder_title = str(awaiting.get("folder_title") or "")
            added, skipped = add_telegram_from_text(db, chat_id, text)
            clear_awaiting(context)
            await update.message.reply_text(
                format_add_report(
                    folder_title=folder_title or None,
                    added=added,
                    skipped=skipped,
                ),
                reply_markup=sources_keyboard(db.list_sources(chat_id)),
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
                added, skipped = add_telegram_from_text(db, chat_id, text)
                clear_awaiting(context)
                await update.message.reply_text(
                    format_add_report(
                        folder_title=None, added=added, skipped=skipped
                    ),
                    reply_markup=sources_keyboard(db.list_sources(chat_id)),
                )
                return

            source_type, identifier, title = parse_add_args(
                ["telegram", *text.split()]
            )
            source = add_single_source(db, chat_id, source_type, identifier, title)
            clear_awaiting(context)
            await update.message.reply_text(
                f"Добавлен канал #{source.id}: {source.title}\n"
                f"{source.identifier}",
                reply_markup=sources_keyboard(db.list_sources(chat_id)),
            )
            return

        if kind == "topic":
            topics = parse_topic_args(text.split())
            added: list[str] = []
            for topic in topics:
                try:
                    db.add_topic(chat_id, topic)
                    added.append(topic)
                except ValueError:
                    pass
            clear_awaiting(context)
            if not added:
                await update.message.reply_text(
                    "Все указанные темы уже были добавлены.",
                    reply_markup=topics_keyboard(db.list_topic_rows(chat_id)),
                )
                return
            await update.message.reply_text(
                "Добавлены темы: "
                + ", ".join(added)
                + "\n\n"
                + topics_text(db, chat_id),
                reply_markup=topics_keyboard(db.list_topic_rows(chat_id)),
            )
            return
    except ValueError as exc:
        await update.message.reply_text(f"{exc}\nПопробуйте ещё раз или /cancel")


async def cancel_awaiting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_awaiting(context)
    if update.message:
        await update.message.reply_text(
            "Отменено.",
            reply_markup=_reply_kb(update),
        )
        await show_main_menu(update, context)
