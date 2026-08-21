from __future__ import annotations

import logging
from datetime import time, timezone

from telegram.ext import Application, ContextTypes

from bot.db import Database
from bot.digest import DigestService
from bot.keyboards import digest_page_keyboard
from bot.menu import DIGEST_SESSIONS_KEY

logger = logging.getLogger(__name__)


async def send_weekly_digests(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job: push weekly top-by-reactions digests to opted-in users."""
    db: Database = context.application.bot_data["db"]
    digest: DigestService = context.application.bot_data["digest"]
    user_ids = db.list_weekly_digest_users()
    logger.info("Weekly digest job: %s users", len(user_ids))

    for user_id in user_ids:
        try:
            items, errors, topics, days_used, analysis = await digest.collect_for_user(
                user_id, days=7, mode="weekly"
            )
            pages = digest.format_digest(
                analysis, days_used, errors=errors, topics=topics
            )
            if not pages:
                continue
            sessions = context.application.bot_data.setdefault(DIGEST_SESSIONS_KEY, {})
            sessions[user_id] = {"pages": pages, "page": 0}
            markup = digest_page_keyboard(0, len(pages)) if len(pages) > 1 else None
            await context.bot.send_message(
                chat_id=user_id,
                text=pages[0],
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=markup,
            )
            digest.mark_digest_delivered(user_id, items)
        except Exception:  # noqa: BLE001
            logger.exception("Weekly digest failed for user %s", user_id)


def schedule_jobs(app: Application) -> None:
    """Register recurring jobs on the PTB JobQueue."""
    settings = app.bot_data["settings"]
    queue = app.job_queue
    if queue is None:
        logger.warning("JobQueue unavailable — weekly digests will not be scheduled")
        return

    queue.run_daily(
        send_weekly_digests,
        time=time(
            hour=settings.weekly_digest_hour_utc,
            minute=0,
            tzinfo=timezone.utc,
        ),
        days=(settings.weekly_digest_weekday,),
        name="weekly_digest",
    )
    logger.info(
        "Scheduled weekly digest: weekday=%s hour_utc=%s",
        settings.weekly_digest_weekday,
        settings.weekly_digest_hour_utc,
    )
