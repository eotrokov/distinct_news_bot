from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    db_path: str
    log_level: str
    digest_limit: int
    digest_page_size: int
    fetch_timeout_seconds: float
    default_lookback_hours: int
    default_digest_days: int
    summary_max_sentences: int

    @classmethod
    def from_env(cls) -> "Settings":
        token = _env("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

        lookback_hours = max(
            1, int(_env("DEFAULT_LOOKBACK_HOURS", "24") or "24")
        )
        digest_days_raw = _env("DEFAULT_DIGEST_DAYS")
        if digest_days_raw:
            digest_days = max(1, int(digest_days_raw))
        else:
            digest_days = max(1, round(lookback_hours / 24))

        return cls(
            telegram_bot_token=token,
            db_path=_env("BOT_DB", "data/bot.sqlite3") or "data/bot.sqlite3",
            log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
            digest_limit=max(1, int(_env("DIGEST_LIMIT", "30") or "30")),
            digest_page_size=max(1, int(_env("DIGEST_PAGE_SIZE", "10") or "10")),
            fetch_timeout_seconds=float(_env("FETCH_TIMEOUT_SECONDS", "20") or "20"),
            default_lookback_hours=lookback_hours,
            default_digest_days=digest_days,
            summary_max_sentences=max(
                1, int(_env("SUMMARY_MAX_SENTENCES", "3") or "3")
            ),
        )
