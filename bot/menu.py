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
    sources_keyboard,
    topics_keyboard,
)
from bot.topics import parse_topic_args

logger = logging.getLogger(__name__)

AWAITING_KEY = "awaiting"
DIGEST_SESSIONS_KEY = "digest_sessions"

MENU_TEXT = (
    "SEO-выжимка из ваших Telegram-каналов.\n"
    "По умолчанию — последние 3 дня (/news 5 — за 5).\n"
    "Больше 10 пунктов — листайте ◀ ▶.\n"
    "Темы: ✅ показывать / 🚫 скрывать."
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
            "Каналов пока нет.\n"
            f"{quota}\n"
            "Нажмите «Добавить канал» или /add @channel"
        )
    lines = [quota, "", "Ваши каналы (нажмите, чтобы удалить):"]
    active, paused = db.list_active_sources(user_id, settings.free_source_limit)
    active_ids = {s.id for s in active}
    for s in sources:
        mark = "" if s.id in active_ids else " ⏸"
        lines.append(f"#{s.id} {s.title}{mark}\n  {s.identifier}")
    if paused:
        lines.append("\n⏸ — на паузе, пока нет оплаченного слота.")
    return "\n".join(lines)


def topics_text(db: Database, user_id: int) -> str:
    rows = db.list_topic_rows(user_id)
    include = [(i, t) for i, t, k in rows if k == "include"]
    exclude = [(i, t) for i, t, k in rows if k == "exclude"]
    if not rows:
        return (
            "Фильтры тем не заданы — в выжимку попадает всё "
            "(кроме стоп-слов/рекламы).\n\n"
            "✅ Показывать — белый список (только эти темы)\n"
            "🚫 Скрывать — чёрный список (эти темы не показывать)\n\n"
            "Команды: /topic + seo · /topic - крипта\n"
            "Или кнопки ниже."
        )
    lines = [
        "Фильтры тем:",
        "",
        "✅ Показывать (если список не пуст — только эти):",
    ]
    if include:
        for _, topic in include:
            lines.append(f"  • {topic}")
    else:
        lines.append("  — нет (показываем всё, кроме скрытых)")
    lines.append("")
    lines.append("🚫 Скрывать (не попадут в выжимку):")
    if exclude:
        for _, topic in exclude:
            lines.append(f"  • {topic}")
    else:
        lines.append("  — нет")
    lines.append("")
    lines.append("Нажмите тему, чтобы удалить.")
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
        try:
            page = int(data.split(":")[2])
        except (IndexError, ValueError):
            await query.answer()
            return
        pages = _get_digest_pages(context, user_id)
        if not pages:
            await query.answer(
                "Выжимка устарела — нажмите «Выжимка» ещё раз.",
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
            "Служебные метки сброшены. На период выжимки это не влияет — "
            "задайте его через /news [дни] (по умолчанию 3).",
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
        set_awaiting(context, {"kind": "source", "type": "telegram"})
        prompt = SOURCE_PROMPTS["telegram"]
        await query.edit_message_text(
            f"{prompt}\n\nИли /cancel чтобы отменить.",
            reply_markup=back_home_keyboard(),
        )
        return
    if data.startswith("m:src_type:"):
        # Legacy callbacks → always Telegram.
        set_awaiting(context, {"kind": "source", "type": "telegram"})
        prompt = SOURCE_PROMPTS["telegram"]
        await query.edit_message_text(
            f"{prompt}\n\nИли /cancel чтобы отменить.",
            reply_markup=back_home_keyboard(),
        )
        return
    if data.startswith("m:src_del:"):
        source_id = int(data.split(":")[2])
        ok = db.remove_source(user_id, source_id)
        note = f"Канал #{source_id} удалён.\n\n" if ok else "Канал не найден.\n\n"
        text = note + sources_text(db, settings, user_id)
        await query.edit_message_text(
            text, reply_markup=_sources_markup(db, settings, user_id)
        )
        return
    if data == "m:topic_add" or data.startswith("m:topic_add:"):
        kind = "include"
        if data.startswith("m:topic_add:"):
            kind = data.split(":")[2]
            if kind not in {"include", "exclude"}:
                kind = "include"
        set_awaiting(context, {"kind": "topic", "topic_kind": kind})
        if kind == "exclude":
            prompt = (
                "Пришлите темы для 🚫 СКРЫВАТЬ (через запятую/пробел).\n"
                "Пример: крипта розыгрыш\n\n/cancel — отмена."
            )
        else:
            prompt = (
                "Пришлите темы для ✅ ПОКАЗЫВАТЬ (через запятую/пробел).\n"
                "Пример: seo алгоритм\n\n/cancel — отмена."
            )
        await query.edit_message_text(prompt, reply_markup=back_home_keyboard())
        return
    if data.startswith("m:topic_del:"):
        topic_id = int(data.split(":")[2])
        removed = db.remove_topic_by_id(user_id, topic_id)
        if removed:
            topic, kind = removed
            mark = "✅" if kind == "include" else "🚫"
            note = f"Тема {mark} «{topic}» удалена.\n\n"
        else:
            note = "Тема не найдена.\n\n"
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
            "Служебные метки сброшены. На период выжимки это не влияет — "
            "задайте его через /news [дни] (по умолчанию 3).",
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
                f"Добавлен канал #{source.id}: {source.title}\n"
                f"{source.identifier}",
                reply_markup=_sources_markup(db, settings, user_id),
            )
            return

        if kind == "topic":
            topic_kind = str(awaiting.get("topic_kind") or "include")
            if topic_kind not in {"include", "exclude"}:
                topic_kind = "include"
            topics = parse_topic_args(text.split())
            added: list[str] = []
            for topic in topics:
                try:
                    db.add_topic(user_id, topic, kind=topic_kind)
                    added.append(topic)
                except ValueError:
                    pass
            clear_awaiting(context)
            mark = "✅" if topic_kind == "include" else "🚫"
            if not added:
                await update.message.reply_text(
                    "Все указанные темы уже были добавлены.",
                    reply_markup=topics_keyboard(db.list_topic_rows(user_id)),
                )
                return
            await update.message.reply_text(
                f"Добавлены {mark}: "
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
    if source_type != "telegram":
        raise ValueError("Пока поддерживаются только публичные Telegram-каналы.")
    identifier = normalize_telegram_handle(identifier)
    if not title:
        title = f"@{identifier.lstrip('@').split('/')[-1]}"
    return "telegram", identifier, title


def _pending_from_text(source_type: str, raw: str) -> dict[str, str]:
    source_type, identifier, title = parse_add_args(["telegram", *raw.split()])
    source_type, identifier, title = _normalize_source_args(
        source_type, identifier, title, raw=raw
    )
    return dump_pending_source(source_type, identifier, title)


def _add_source_from_text(
    db: Database, user_id: int, source_type: str, raw: str
):
    # Accept bare @channel from the prompt.
    parts = raw.split()
    if parts and parts[0].lower() not in {"telegram", "tg", "channel"}:
        args = ["telegram", *parts]
    else:
        args = parts
    source_type, identifier, title = parse_add_args(args)
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
