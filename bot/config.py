from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    rsshub_base_url: str | None
    default_lookback_hours: int
    telegram_api_id: int | None
    telegram_api_hash: str | None
    telegram_session_path: str

    @classmethod
    def from_env(cls) -> "Settings":
        token = _env("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

        db_path = _env("BOT_DB", "data/bot.sqlite3") or "data/bot.sqlite3"
        api_id_raw = _env("TELEGRAM_API_ID")
        api_id = int(api_id_raw) if api_id_raw else None
        session_default = str(Path(db_path).parent / "telethon.session")

        return cls(
            telegram_bot_token=token,
            db_path=db_path,
            log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
            digest_limit=max(1, int(_env("DIGEST_LIMIT", "30") or "30")),
            fetch_timeout_seconds=float(_env("FETCH_TIMEOUT_SECONDS", "20") or "20"),
            rsshub_base_url=_env("RSSHUB_BASE_URL"),
            default_lookback_hours=max(
                1, int(_env("DEFAULT_LOOKBACK_HOURS", "24") or "24")
            ),
            telegram_api_id=api_id,
            telegram_api_hash=_env("TELEGRAM_API_HASH"),
            telegram_session_path=_env("TELEGRAM_SESSION_PATH", session_default)
            or session_default,
        )
