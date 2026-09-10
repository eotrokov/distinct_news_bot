from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.db import Database
from bot.digest import DigestService
from bot.keyboards import back_home_keyboard
from bot.schedule import UserSchedule

logger = logging.getLogger(__name__)

# Check every minute so :55 schedules fire close to the requested time.
SCHEDULE_JOB_INTERVAL_SECONDS = 60

# Prevent overlapping ticks from double-sending while a collect is in flight.
_IN_FLIGHT: set[int] = set()

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


async def _send_digest_message(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    text: str,
    reply_markup: Any,
) -> None:
    """Send digest HTML; fall back to plain text if Telegram rejects the markup."""
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )
    except BadRequest as exc:
        msg = str(exc).lower()
        if "parse" not in msg and "entity" not in msg:
            raise
        logger.warning(
            "HTML parse failed for chat %s (%s) — retrying as plain text",
            chat_id,
            exc,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=_strip_html(text),
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )


async def deliver_digest_to_user(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    days: int | None = None,
    only_unseen: bool = False,
    preface: str | None = None,
    consume_quota: bool = True,
    since=None,
    until=None,
) -> bool:
    """Collect and send a digest to a chat.

    ``user_id`` is the workspace id (private chat.id == user.id, or group chat.id).
    Returns True if a message was sent.
    Returns False if skipped (quota) or collect failed after notifying the user.
    Raises on Telegram send failure so the caller can retry without marking sent.
    """
    digest: DigestService = context.application.bot_data["digest"]
    db: Database = context.application.bot_data["db"]
    if consume_quota:
        allowed, _ent = db.consume_digest_quota(user_id)
        if not allowed:
            logger.info(
                "Skip scheduled digest for user %s — daily quota exhausted",
                user_id,
            )
            return False
    try:
        items, errors, topics, days_used, analysis = await digest.collect_for_user(
            user_id,
            days=days,
            only_unseen=only_unseen,
            since=since,
            until=until,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled digest failed for user %s", user_id)
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="Не удалось собрать запланированную сводку. Попробуйте «Сводка» вручную.",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Could not notify user %s about digest failure", user_id)
        return False

    pages = digest.format_digest(
        analysis, days_used, errors=errors, topics=topics
    )
    text = pages[0]
    if preface:
        text = f"{preface}\n\n{text}"

    sessions = context.application.bot_data.setdefault("digest_sessions", {})
    sessions[user_id] = {"pages": pages, "page": 0}
    try:
        db.save_digest_session(user_id, pages, page=0)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to persist scheduled digest session for %s", user_id)

    markup = back_home_keyboard()
    if len(pages) > 1:
        from bot.keyboards import digest_page_keyboard

        markup = digest_page_keyboard(0, len(pages))

    await _send_digest_message(
        context, chat_id=user_id, text=text, reply_markup=markup
    )
    # Only mark seen / log after Telegram accepted the message.
    digest.mark_digest_delivered(user_id, items, trigger="scheduled")
    return True


async def scheduled_digest_tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    due = db.list_due_schedules()
    if not due:
        return
    logger.info("Schedule tick: %s user(s) due", len(due))
    for schedule in due:
        await _send_scheduled_digest(context, schedule)


async def _send_scheduled_digest(
    context: ContextTypes.DEFAULT_TYPE, schedule: UserSchedule
) -> None:
    db: Database = context.application.bot_data["db"]
    user_id = schedule.user_id
    if user_id in _IN_FLIGHT:
        logger.info("Skip schedule for %s — already in flight", user_id)
        return

    local_date = schedule.local_date_str()
    since, until = schedule.previous_local_day_bounds()
    yday = schedule.local_now().date() - timedelta(days=1)
    preface = (
        f"📅 Авто-сводка за {yday.isoformat()} · "
        f"{schedule.format_time()} ({schedule.format_offset()})"
    )

    _IN_FLIGHT.add(user_id)
    try:
        try:
            sent = await deliver_digest_to_user(
                context,
                user_id,
                days=1,
                only_unseen=False,
                preface=preface,
                since=since,
                until=until,
            )
        except Exception:  # noqa: BLE001
            # Do NOT mark sent — next minute tick can retry.
            logger.exception(
                "Failed scheduled digest delivery for user %s — will retry",
                user_id,
            )
            return

        # Mark after success OR intentional skip (quota / collect notify),
        # so we neither miss the day on a flaky send nor spam every minute.
        db.mark_schedule_sent(user_id, local_date)
        if sent:
            logger.info(
                "Scheduled digest delivered to %s for %s", user_id, local_date
            )
        else:
            logger.info(
                "Scheduled digest marked done for %s for %s (skipped)",
                user_id,
                local_date,
            )
    finally:
        _IN_FLIGHT.discard(user_id)


def setup_schedule_jobs(app: Any) -> None:
    jq = app.job_queue
    if jq is None:
        logging.getLogger(__name__).warning(
            "JobQueue is unavailable — scheduled digests disabled"
        )
        return
    jq.run_repeating(
        scheduled_digest_tick,
        interval=SCHEDULE_JOB_INTERVAL_SECONDS,
        first=20,
        name="scheduled_digest_tick",
    )
    logging.getLogger(__name__).info(
        "Scheduled digest job registered (every %ss)",
        SCHEDULE_JOB_INTERVAL_SECONDS,
    )
