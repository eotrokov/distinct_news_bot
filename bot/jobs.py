from __future__ import annotations

import logging
from typing import Any

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.db import Database
from bot.digest import DigestService
from bot.keyboards import back_home_keyboard
from bot.schedule import UserSchedule

logger = logging.getLogger(__name__)

SCHEDULE_JOB_INTERVAL_SECONDS = 300  # 5 minutes


async def deliver_digest_to_user(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    days: int | None = None,
    only_unseen: bool = False,
    preface: str | None = None,
    consume_quota: bool = True,
) -> bool:
    """Collect and send a digest to a private chat (chat_id == user_id).

    Returns True if a message was sent.
    """
    digest: DigestService = context.application.bot_data["digest"]
    db: Database = context.application.bot_data["db"]
    if consume_quota:
        allowed, ent = db.consume_digest_quota(user_id)
        if not allowed:
            logger.info(
                "Skip scheduled digest for user %s — daily quota exhausted",
                user_id,
            )
            return False
    try:
        items, errors, topics, days_used, analysis = await digest.collect_for_user(
            user_id, days=days, only_unseen=only_unseen
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

    digest.mark_digest_delivered(user_id, items)
    markup = back_home_keyboard()
    if len(pages) > 1:
        from bot.keyboards import digest_page_keyboard

        markup = digest_page_keyboard(0, len(pages))

    await context.bot.send_message(
        chat_id=user_id,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=markup,
    )
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
    local_date = schedule.local_date_str()
    # Mark first to avoid double-send on overlapping ticks if send is slow.
    db.mark_schedule_sent(user_id, local_date)
    preface = (
        f"📅 Авто-сводка · {schedule.hour:02d}:00 ({schedule.format_offset()})"
    )
    try:
        await deliver_digest_to_user(
            context,
            user_id,
            only_unseen=False,
            preface=preface,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed scheduled digest delivery for user %s", user_id)


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
