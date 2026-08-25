from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from telegram import LabeledPrice, Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.db import Database
from bot.plans import PLAN_CATALOG, SUBSCRIPTION_PERIOD_SECONDS, format_plan_status

logger = logging.getLogger(__name__)


def stars_price_for(plan: str, settings: Settings) -> int:
    if plan == "pro":
        return settings.pro_stars_price
    if plan == "plus":
        return settings.plus_stars_price
    return PLAN_CATALOG[plan].stars_price


async def send_plan_invoice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    plan: str,
) -> None:
    if plan not in {"pro", "plus"}:
        raise ValueError("Доступны планы: pro, plus")
    if not update.effective_user or not update.effective_message:
        return
    settings: Settings = context.application.bot_data["settings"]
    user_id = update.effective_user.id
    price = stars_price_for(plan, settings)
    title = f"Distinct News {PLAN_CATALOG[plan].title}"
    description = (
        f"{PLAN_CATALOG[plan].title}: до {PLAN_CATALOG[plan].max_sources} каналов, "
        f"{PLAN_CATALOG[plan].max_digests_per_day} сводок/день, расписание. 30 дней."
    )
    payload = f"plan:{plan}:{user_id}"
    await context.bot.send_invoice(
        chat_id=user_id,
        title=title,
        description=description,
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(PLAN_CATALOG[plan].title, price)],
        provider_token="",
        api_kwargs={"subscription_period": SUBSCRIPTION_PERIOD_SECONDS},
    )


async def on_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if not query:
        return
    payload = query.invoice_payload or ""
    ok = payload.startswith("plan:pro:") or payload.startswith("plan:plus:")
    await query.answer(ok=ok, error_message=None if ok else "Неверный платёж")


async def on_successful_payment(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not update.message.successful_payment or not update.effective_user:
        return
    payment = update.message.successful_payment
    payload = payment.invoice_payload or ""
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != "plan" or parts[1] not in {"pro", "plus"}:
        await update.message.reply_text("Платёж получен, но план не распознан. Напишите в поддержку.")
        return
    plan = parts[1]
    db: Database = context.application.bot_data["db"]
    user_id = update.effective_user.id

    expires = payment.subscription_expiration_date
    if expires is None:
        expires = datetime.now(timezone.utc) + timedelta(seconds=SUBSCRIPTION_PERIOD_SECONDS)
    elif expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    ent = db.set_plan(user_id, plan, expires_at=expires)
    logger.info(
        "Activated plan=%s user=%s expires=%s charge=%s",
        plan,
        user_id,
        expires.isoformat(),
        payment.telegram_payment_charge_id,
    )
    await update.message.reply_text(
        f"Оплата прошла. План {PLAN_CATALOG[plan].title} активен.\n\n"
        + format_plan_status(ent)
    )
