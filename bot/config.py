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
    fetch_timeout_seconds: float
    default_lookback_hours: int

    @classmethod
    def from_env(cls) -> "Settings":
        token = _env("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

        return cls(
            telegram_bot_token=token,
            db_path=_env("BOT_DB", "data/bot.sqlite3") or "data/bot.sqlite3",
            log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
            digest_limit=max(1, int(_env("DIGEST_LIMIT", "30") or "30")),
            fetch_timeout_seconds=float(_env("FETCH_TIMEOUT_SECONDS", "20") or "20"),
            default_lookback_hours=max(
                1, int(_env("DEFAULT_LOOKBACK_HOURS", "24") or "24")
            ),
        )
