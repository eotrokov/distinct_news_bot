from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _parse_admin_ids(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return frozenset(ids)


def _resolve_ai_api_key() -> str | None:
    provider = (_env("AI_PROVIDER", "gemini") or "gemini").lower()
    if provider == "groq":
        return _env("GROQ_API_KEY")
    return _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")


def _resolve_ai_model() -> str:
    provider = (_env("AI_PROVIDER", "gemini") or "gemini").lower()
    if _env("AI_MODEL"):
        return _env("AI_MODEL") or ""
    if provider == "groq":
        return "llama-3.3-70b-versatile"
    return "gemini-2.0-flash"


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    db_path: str
    log_level: str
    digest_limit: int
    digest_page_size: int
    fetch_timeout_seconds: float
    fetch_concurrency: int
    fetch_cache_ttl_seconds: float
    default_lookback_hours: int
    default_digest_days: int
    summary_max_sentences: int
    admin_user_ids: frozenset[int]
    pro_stars_price: int
    plus_stars_price: int
    ai_summary_enabled: bool
    ai_provider: str
    ai_api_key: str | None
    ai_model: str
    ai_max_concurrent: int
    ai_timeout_seconds: float

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
            fetch_concurrency=max(1, int(_env("FETCH_CONCURRENCY", "5") or "5")),
            fetch_cache_ttl_seconds=float(
                _env("FETCH_CACHE_TTL_SECONDS", "120") or "120"
            ),
            default_lookback_hours=lookback_hours,
            default_digest_days=digest_days,
            summary_max_sentences=max(
                2, int(_env("SUMMARY_MAX_SENTENCES", "2") or "2")
            ),
            admin_user_ids=_parse_admin_ids(_env("ADMIN_USER_IDS")),
            pro_stars_price=max(1, int(_env("PRO_STARS_PRICE", "350") or "350")),
            plus_stars_price=max(1, int(_env("PLUS_STARS_PRICE", "700") or "700")),
            ai_summary_enabled=_env("AI_SUMMARY_ENABLED", "0")
            not in {"0", "false", "False", "no", "off"},
            ai_provider=(_env("AI_PROVIDER", "gemini") or "gemini").lower(),
            ai_api_key=_resolve_ai_api_key(),
            ai_model=_resolve_ai_model(),
            ai_max_concurrent=max(
                1, min(10, int(_env("AI_MAX_CONCURRENT", "4") or "4"))
            ),
            ai_timeout_seconds=float(_env("AI_TIMEOUT_SECONDS", "15") or "15"),
        )
