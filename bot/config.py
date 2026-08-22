from __future__ import annotations

import os
from dataclasses import dataclass

# Stop words for TF-IDF body similarity (do NOT use for filtering posts).
STOP_WORDS: list[str] = [
    "это",
    "все",
    "так",
    "для",
    "на",
    "с",
    "по",
    "the",
    "this",
    "that",
]

# Phrases that mark promo / noise / intro fluff — post is dropped from digest.
STOP_PHRASES: list[str] = [
    "всем привет",
    "доброе утро",
    "добрый день",
    "добрый вечер",
    "не забудьте подписаться",
    "подписывайтесь",
    "подпишись на канал",
    "подпишитесь",
    "ставьте 🔥",
    "ставьте лайк",
    "жми лайк",
    "ставьте огонек",
    "ставьте огонёк",
    "пишите в комментах",
    "пишите в комментариях",
    "ссылка в описании",
    "ссылка в шапке",
    "ссылка в био",
    "переходи по ссылке",
    "переходите по ссылке",
    "реклама",
    "erid",
    "промокод",
    "успей купить",
    "только сегодня",
    "бесплатная подписка",
    "партнерский материал",
    "партнёрский материал",
    "по заявкам",
    "сегодня мы разберем",
    "сегодня мы разберём",
    "наш курс",
    "запись на курс",
    "интенсив для",
    "buy now",
    "limited offer",
    "subscribe now",
    "follow us",
]

# Single words/tokens: if found in title/summary, post is dropped.
BLOCK_WORDS: list[str] = [
    "розыгрыш",
    "giveaway",
    "конкурс",
    "промокод",
    "инфобиз",
    "марафон",
    "вебинар",
    "подписывайтесь",
    "подпишись",
    "лайкните",
    "репост",
    "реклама",
    "erid",
    "coupon",
]

IMPORTANT_KEYWORDS: list[str] = [
    "update",
    "official",
    "заявил",
    "подтвердил",
    "объявил",
]

KEYWORD_CATEGORIES: dict[str, list[str]] = {
    "🔄 Апдейты алгоритмов": [
        "core update",
        "spam update",
        "алгоритм",
        "ранжирование",
    ],
    "🔍 Выдача и SERP-фичи": [
        "serp",
        "snippet",
        "ai overview",
        "нейроответ",
    ],
    "🛠 Технический SEO": [
        "индексация",
        "краулинг",
        "core web vitals",
        "robots",
    ],
    "📊 Инструменты и сервисы": [
        "ahrefs",
        "semrush",
        "search console",
        "вебмастер",
    ],
    "🤖 AI / нейропоиск": [
        "llm",
        "ai",
        "нейросеть",
        "gep",
    ],
    "📈 Исследования и кейсы": [
        "исследование",
        "кейс",
        "трафик",
        "эксперимент",
    ],
}


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
    rsshub_base_url: str | None
    default_digest_days: int
    # Kept for backward compatibility with older .env files.
    default_lookback_hours: int
    free_source_limit: int
    stars_per_extra_source: int
    paid_slot_days: int
    summary_max_sentences: int
    weekly_top_limit: int
    weekly_digest_hour_utc: int
    weekly_digest_weekday: int
    ai_summary_enabled: bool
    groq_api_key: str | None
    ai_model: str
    ai_max_concurrent: int
    ai_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        token = _env("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

        digest_days = max(1, int(_env("DEFAULT_DIGEST_DAYS", "3") or "3"))
        lookback_hours = max(
            1, int(_env("DEFAULT_LOOKBACK_HOURS", str(digest_days * 24)) or str(digest_days * 24))
        )

        return cls(
            telegram_bot_token=token,
            db_path=_env("BOT_DB", "data/bot.sqlite3") or "data/bot.sqlite3",
            log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
            digest_limit=max(1, int(_env("DIGEST_LIMIT", "30") or "30")),
            digest_page_size=max(1, int(_env("DIGEST_PAGE_SIZE", "10") or "10")),
            fetch_timeout_seconds=float(_env("FETCH_TIMEOUT_SECONDS", "20") or "20"),
            rsshub_base_url=_env("RSSHUB_BASE_URL"),
            default_digest_days=digest_days,
            default_lookback_hours=lookback_hours,
            free_source_limit=max(1, int(_env("FREE_SOURCE_LIMIT", "20") or "20")),
            stars_per_extra_source=max(
                1, int(_env("STARS_PER_EXTRA_SOURCE", "10") or "10")
            ),
            paid_slot_days=max(1, int(_env("PAID_SLOT_DAYS", "30") or "30")),
            summary_max_sentences=max(
                2, int(_env("SUMMARY_MAX_SENTENCES", "3") or "3")
            ),
            weekly_top_limit=max(1, int(_env("WEEKLY_TOP_LIMIT", "10") or "10")),
            weekly_digest_hour_utc=max(
                0, min(23, int(_env("WEEKLY_DIGEST_HOUR_UTC", "9") or "9"))
            ),
            weekly_digest_weekday=max(
                0, min(6, int(_env("WEEKLY_DIGEST_WEEKDAY", "0") or "0"))
            ),
            ai_summary_enabled=_env("AI_SUMMARY_ENABLED", "1") not in {
                "0",
                "false",
                "False",
                "no",
                "off",
            },
            groq_api_key=_env("GROQ_API_KEY"),
            ai_model=_env("AI_MODEL", "llama-3.3-70b-versatile")
            or "llama-3.3-70b-versatile",
            ai_max_concurrent=max(
                1, min(10, int(_env("AI_MAX_CONCURRENT", "4") or "4"))
            ),
            ai_timeout_seconds=float(_env("AI_TIMEOUT_SECONDS", "15") or "15"),
        )
