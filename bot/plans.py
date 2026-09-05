from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Temporary kill-switch for paid plans / quotas. Re-enable via MONETIZATION_ENABLED=1.
_MONETIZATION_ENABLED = False


def set_monetization_enabled(enabled: bool) -> None:
    global _MONETIZATION_ENABLED
    _MONETIZATION_ENABLED = enabled


def is_monetization_enabled() -> bool:
    return _MONETIZATION_ENABLED


@dataclass(frozen=True)
class PlanLimits:
    key: str
    title: str
    max_sources: int
    max_digests_per_day: int
    allow_schedule: bool
    max_digest_days: int
    stars_price: int = 0  # 0 = not purchasable


PLAN_CATALOG: dict[str, PlanLimits] = {
    "trial": PlanLimits(
        key="trial",
        title="Trial",
        max_sources=30,
        max_digests_per_day=10,
        allow_schedule=True,
        max_digest_days=7,
    ),
    "free": PlanLimits(
        key="free",
        title="Free",
        max_sources=15,
        max_digests_per_day=10,
        allow_schedule=True,
        max_digest_days=7,
    ),
    "pro": PlanLimits(
        key="pro",
        title="Pro",
        max_sources=30,
        max_digests_per_day=20,
        allow_schedule=True,
        max_digest_days=7,
        stars_price=350,
    ),
    "plus": PlanLimits(
        key="plus",
        title="Plus",
        max_sources=100,
        max_digests_per_day=50,
        allow_schedule=True,
        max_digest_days=14,
        stars_price=700,
    ),
}

# Used while monetization is off: no practical quotas.
OPEN_LIMITS = PlanLimits(
    key="open",
    title="Open",
    max_sources=10_000,
    max_digests_per_day=10_000,
    allow_schedule=True,
    max_digest_days=30,
)

TRIAL_DAYS = 7
SUBSCRIPTION_PERIOD_SECONDS = 30 * 24 * 60 * 60  # Telegram Stars monthly
MONETIZATION_OFF_MESSAGE = (
    "Оплата и лимиты подписки временно отключены. "
    "Все функции доступны без оплаты."
)


@dataclass(frozen=True)
class UserEntitlement:
    user_id: int
    plan: str
    plan_expires_at: datetime | None
    trial_started_at: datetime | None
    digests_today: int
    digest_day: str | None

    def effective_plan(self, now: datetime | None = None) -> str:
        if not is_monetization_enabled():
            return "open"
        now = now or datetime.now(timezone.utc)
        plan = self.plan if self.plan in PLAN_CATALOG else "free"
        if plan == "trial":
            started = self.trial_started_at or now
            if started + timedelta(days=TRIAL_DAYS) < now:
                return "free"
            return "trial"
        if plan in {"pro", "plus"}:
            if self.plan_expires_at and self.plan_expires_at < now:
                return "free"
            return plan
        return "free"

    def limits(self, now: datetime | None = None) -> PlanLimits:
        if not is_monetization_enabled():
            return OPEN_LIMITS
        return PLAN_CATALOG[self.effective_plan(now)]


def format_plan_status(ent: UserEntitlement) -> str:
    now = datetime.now(timezone.utc)
    if not is_monetization_enabled():
        return (
            f"⭐️ Подписка: {OPEN_LIMITS.title}\n"
            f"{MONETIZATION_OFF_MESSAGE}\n"
            f"Источники: без лимита\n"
            "SEO-блоги (RSS): в сводке\n"
            f"Сводки: без дневного лимита (сегодня {ent.digests_today})\n"
            f"Окно: до {OPEN_LIMITS.max_digest_days} дн.\n"
            "Расписание: да"
        )
    key = ent.effective_plan(now)
    limits = PLAN_CATALOG[key]
    lines = [
        f"⭐️ Подписка: {limits.title}",
        f"Источники: до {limits.max_sources}",
        "SEO-блоги (RSS): в сводке, слоты не занимают",
        f"Сводки: до {limits.max_digests_per_day}/день (сегодня {ent.digests_today})",
        f"Окно: до {limits.max_digest_days} дн.",
        f"Расписание: {'да' if limits.allow_schedule else 'нет'}",
    ]
    if key == "trial" and ent.trial_started_at:
        ends = ent.trial_started_at + timedelta(days=TRIAL_DAYS)
        left = max(0, (ends - now).days)
        lines.append(f"Trial ещё ~{left} дн.")
    elif key in {"pro", "plus"} and ent.plan_expires_at:
        lines.append(f"До: {ent.plan_expires_at.date().isoformat()}")
    lines.extend(
        [
            "",
            "Купить / продлить:",
            f"/buy pro — Pro ({PLAN_CATALOG['pro'].stars_price} ⭐ / мес)",
            f"/buy plus — Plus ({PLAN_CATALOG['plus'].stars_price} ⭐ / мес)",
            "/plan — этот статус",
        ]
    )
    return "\n".join(lines)
