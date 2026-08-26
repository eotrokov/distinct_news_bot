from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone


@dataclass(frozen=True)
class UserSchedule:
    user_id: int
    enabled: bool
    hour: int
    minute: int = 0
    tz_offset_minutes: int = 180
    last_schedule_date: str | None = None

    def tzinfo(self) -> timezone:
        return timezone(timedelta(minutes=self.tz_offset_minutes))

    def format_offset(self) -> str:
        sign = "+" if self.tz_offset_minutes >= 0 else "-"
        total = abs(self.tz_offset_minutes)
        hours, minutes = divmod(total, 60)
        if minutes:
            return f"UTC{sign}{hours}:{minutes:02d}"
        return f"UTC{sign}{hours}"

    def format_time(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"

    def local_now(self, now: datetime | None = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        return now.astimezone(self.tzinfo())

    def local_date_str(self, now: datetime | None = None) -> str:
        return self.local_now(now).date().isoformat()

    def previous_local_day_bounds(
        self, now: datetime | None = None
    ) -> tuple[datetime, datetime]:
        """UTC-aware [start, end) for the previous calendar day in the user TZ."""
        local = self.local_now(now)
        yesterday: date = local.date() - timedelta(days=1)
        start_local = datetime.combine(yesterday, time.min, tzinfo=self.tzinfo())
        end_local = datetime.combine(local.date(), time.min, tzinfo=self.tzinfo())
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    def due_now(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        local = self.local_now(now)
        today = local.date().isoformat()
        if self.last_schedule_date == today:
            return False
        # Fire once the local clock has reached the scheduled time today.
        return (local.hour, local.minute) >= (self.hour, self.minute)


def parse_schedule_time(raw: str) -> tuple[int, int]:
    """Parse ``9``, ``9:55``, ``09:55`` into (hour, minute)."""
    text = raw.strip().lower().replace(".", ":")
    if not text:
        raise ValueError("Укажите время, например 9 или 9:55")
    if ":" in text:
        hour_s, minute_s, *rest = text.split(":")
        if rest:
            raise ValueError("Формат времени: ЧЧ или ЧЧ:ММ")
        hour = int(hour_s)
        minute = int(minute_s)
    else:
        hour = int(text)
        minute = 0
    if not 0 <= hour <= 23:
        raise ValueError("Час должен быть от 0 до 23")
    if not 0 <= minute <= 59:
        raise ValueError("Минуты должны быть от 0 до 59")
    return hour, minute


def parse_tz_offset(raw: str) -> int:
    """Parse +3, UTC+3, +03:30 into minutes east of UTC."""
    text = raw.strip().upper().replace(" ", "")
    if text.startswith("UTC"):
        text = text[3:]
    if not text:
        raise ValueError("Укажите смещение, например +3 или UTC+3")
    sign = 1
    if text[0] == "+":
        text = text[1:]
    elif text[0] == "-":
        sign = -1
        text = text[1:]
    if ":" in text:
        hours_s, minutes_s = text.split(":", 1)
        hours = int(hours_s)
        minutes = int(minutes_s)
    else:
        hours = int(text)
        minutes = 0
    if hours > 14 or minutes not in {0, 30, 45}:
        raise ValueError("Смещение: часы −12…+14, минуты 0/30/45")
    total = sign * (hours * 60 + minutes)
    if total < -12 * 60 or total > 14 * 60:
        raise ValueError("Смещение вне диапазона UTC−12…UTC+14")
    return total


def format_schedule_status(schedule: UserSchedule) -> str:
    if schedule.enabled:
        state = (
            f"включено · каждый день в {schedule.format_time()} "
            f"({schedule.format_offset()})"
        )
    else:
        state = (
            f"выключено · время {schedule.format_time()} "
            f"({schedule.format_offset()})"
        )
    lines = [
        "📅 Расписание авто-сводки",
        state,
        "Содержание: новости за предыдущий календарный день.",
        "",
        "Команды:",
        "/schedule on [время] — включить (по умолчанию 9:55)",
        "/schedule off — выключить",
        "/schedule time 9:55 — сменить время",
        "/schedule tz +3 — часовой пояс",
        "/schedule — этот статус",
        "",
        "Примеры: /schedule on 9:55 · /schedule on 9 · /schedule time 8:30",
    ]
    return "\n".join(lines)
