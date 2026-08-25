from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class UserSchedule:
    user_id: int
    enabled: bool
    hour: int
    tz_offset_minutes: int
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

    def local_now(self, now: datetime | None = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        return now.astimezone(self.tzinfo())

    def local_date_str(self, now: datetime | None = None) -> str:
        return self.local_now(now).date().isoformat()

    def due_now(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        local = self.local_now(now)
        if local.hour != self.hour:
            return False
        today = local.date().isoformat()
        return self.last_schedule_date != today


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
        state = f"включено · каждый день в {schedule.hour:02d}:00 ({schedule.format_offset()})"
    else:
        state = f"выключено · час {schedule.hour:02d}:00 ({schedule.format_offset()})"
    lines = [
        "📅 Расписание авто-сводки",
        state,
        "",
        "Команды:",
        "/schedule on [час] — включить (по умолчанию 9)",
        "/schedule off — выключить",
        "/schedule hour 8 — сменить час (0–23)",
        "/schedule tz +3 — часовой пояс",
        "/schedule — этот статус",
    ]
    return "\n".join(lines)
