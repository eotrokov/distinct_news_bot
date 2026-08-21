from __future__ import annotations

import logging
from typing import Any

from telegram import LabeledPrice, Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.db import Database
from bot.models import SourceType

logger = logging.getLogger(__name__)

PENDING_SOURCE_KEY = "pending_source"
PAYLOAD_BUY_SLOT = "buy_slot"
PAYLOAD_BUY_SLOT_ADD = "buy_slot_add"


class SourceLimitError(Exception):
    """Raised when user needs to buy a paid slot to add another source."""

    def __init__(
        self,
        *,
        current: int,
        limit: int,
        free_limit: int,
        stars: int,
        paid_slots: int,
    ) -> None:
        self.current = current
        self.limit = limit
        self.free_limit = free_limit
        self.stars = stars
        self.paid_slots = paid_slots
        super().__init__(
            f"Лимит источников: {current}/{limit}. "
            f"Бесплатно {free_limit}, далее {stars}⭐ за канал / месяц."
        )


def ensure_can_add_source(db: Database, settings: Settings, user_id: int) -> None:
    current = db.count_sources(user_id)
    paid = db.count_active_paid_slots(user_id)
    limit = settings.free_source_limit + paid
    if current >= limit:
        raise SourceLimitError(
            current=current,
            limit=limit,
            free_limit=settings.free_source_limit,
            stars=settings.stars_per_extra_source,
            paid_slots=paid,
        )


def sources_quota_text(db: Database, settings: Settings, user_id: int) -> str:
    current = db.count_sources(user_id)
    paid = db.count_active_paid_slots(user_id)
    limit = settings.free_source_limit + paid
    lines = [
        f"Слоты: {current}/{limit} "
        f"(бесплатно {settings.free_source_limit}, оплаченных: {paid}).",
        f"Сверх лимита — {settings.stars_per_extra_source}⭐ за канал на "
        f"{settings.paid_slot_days} дн.",
    ]
    expiry = db.latest_paid_slot_expiry(user_id)
    if expiry:
        lines.append(f"Ближайший оплаченный слот до: {expiry.strftime('%d.%m.%Y')}.")
    active, paused = db.list_active_sources(user_id, settings.free_source_limit)
    if paused:
        lines.append(
            f"⚠ На паузе из‑за лимита: {len(paused)} "
            f"(оплатите слот, чтобы снова читать их)."
        )
        _ = active  # silence lint
    return "\n".join(lines)


async def send_slot_invoice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    pending_source: dict[str, Any] | None = None,
) -> None:
    """Send a Telegram Stars invoice for one extra source slot."""
    if not update.effective_user or not update.effective_chat:
        return
    settings: Settings = context.application.bot_data["settings"]
    stars = settings.stars_per_extra_source
    days = settings.paid_slot_days

    if pending_source:
        context.user_data[PENDING_SOURCE_KEY] = pending_source
        payload = PAYLOAD_BUY_SLOT_ADD
    else:
        context.user_data.pop(PENDING_SOURCE_KEY, None)
        payload = PAYLOAD_BUY_SLOT

    title = "Доп. канал на месяц"
    description = (
        f"Слот источника сверх бесплатных {settings.free_source_limit} "
        f"на {days} дней. После оплаты можно добавить ещё один канал."
    )
    prices = [LabeledPrice(label=f"Слот на {days} дн.", amount=stars)]

    chat_id = update.effective_chat.id
    await context.bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",  # required empty for Telegram Stars
        currency="XTR",
        prices=prices,
    )


def parse_pending_source(raw: dict[str, Any] | None) -> tuple[SourceType, str, str] | None:
    if not raw:
        return None
    try:
        source_type = str(raw["source_type"])
        identifier = str(raw["identifier"])
        title = str(raw.get("title") or identifier[:60])
    except (KeyError, TypeError, ValueError):
        return None
    if source_type not in {"telegram", "rss", "ria", "facebook", "twitter"}:
        return None
    return source_type, identifier, title  # type: ignore[return-value]


def dump_pending_source(
    source_type: str, identifier: str, title: str
) -> dict[str, str]:
    return {
        "source_type": source_type,
        "identifier": identifier,
        "title": title,
    }
