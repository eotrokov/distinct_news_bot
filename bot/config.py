from __future__ import annotations

import os
from dataclasses import dataclass

# Stop words for TF-IDF body similarity.
STOP_WORDS: tuple[str, ...] = (
    # Russian
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то",
    "все", "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за",
    "бы", "по", "только", "ее", "мне", "было", "вот", "от", "меня", "еще",
    "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли",
    "если", "уже", "или", "ни", "быть", "был", "него", "до", "вас", "нибудь",
    "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей",
    "может", "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя",
    "их", "чем", "была", "сам", "чтоб", "без", "будто", "чего", "раз", "тоже",
    "себе", "под", "будет", "ж", "тогда", "кто", "этот", "того", "потому",
    "этого", "какой", "совсем", "ним", "здесь", "этом", "один", "почти",
    "мой", "тем", "чтобы", "нее", "сейчас", "были", "куда", "зачем", "сказать",
    "всех", "никогда", "можно", "при", "наконец", "два", "об", "другой", "хоть",
    "после", "над", "больше", "тот", "через", "эти", "нас", "про", "всего",
    "них", "какая", "много", "разве", "три", "эту", "моя", "впрочем", "хорошо",
    "свою", "этой", "перед", "иногда", "лучше", "чуть", "том", "нельзя",
    "такой", "им", "более", "всегда", "конечно", "всю", "между",
    # English
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "as", "by", "with", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall", "can", "need",
    "this", "that", "these", "those", "it", "its", "they", "them", "their",
    "we", "you", "he", "she", "his", "her", "our", "your", "not", "no",
    "yes", "if", "then", "than", "so", "just", "about", "into", "over",
    "after", "before", "between", "under", "again", "further", "once",
    "here", "there", "when", "where", "why", "how", "all", "any", "both",
    "each", "few", "more", "most", "other", "some", "such", "only", "own",
    "same", "than", "too", "very", "s", "t", "don", "now",
)

# Phrases that mark promo / noise / intro fluff.
STOP_PHRASES: tuple[str, ...] = (
    "сегодня мы разберем",
    "сегодня мы разберём",
    "напоминаю",
    "по заявкам",
    "тот самый материал",
    "подписывайтесь",
    "ставьте лайк",
    "реклама",
    "промокод",
    "успей купить",
    "только сегодня",
    "бесплатная подписка",
    "партнерский материал",
    "партнёрский материал",
    "erid",
    "buy now",
    "limited offer",
)

IMPORTANT_KEYWORDS: tuple[str, ...] = (
    "google",
    "гугл",
    "яндекс",
    "seo",
    "поиск",
    "алгоритм",
    "ранжирование",
    "индексац",
    "нейросет",
    "ai",
    "ии",
    "openai",
    "chatgpt",
    "запустил",
    "запустила",
    "объявил",
    "объявила",
    "обновлен",
    "обновление",
    "штраф",
    "бан",
    "утечк",
    "закон",
    "регулир",
    "конфиденц",
    "персональн",
)

KEYWORD_CATEGORIES: dict[str, tuple[str, ...]] = {
    "SEO и поиск": (
        "seo", "google", "гугл", "яндекс", "поиск", "search", "ранжир",
        "индекс", "сниппет", "core update", "алгоритм", "serp",
    ),
    "ИИ и технологии": (
        "ai", "ии", "нейросет", "openai", "chatgpt", "llm", "машинн",
        "model", "gpt", "claude", "gemini",
    ),
    "Маркетинг": (
        "маркетинг", "реклам", "ads", "контекст", "таргет", "бренд",
        "контент", "smm", "email",
    ),
    "Бизнес и продукт": (
        "запустил", "запуск", "продукт", "стартап", "инвест", "сделк",
        "ipo", "финанс", "выручк",
    ),
    "Безопасность и право": (
        "утечк", "взлом", "штраф", "закон", "суд", "персональн", "gdpr",
        "конфиденц", "бан", "блокир",
    ),
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
    fetch_timeout_seconds: float
    rsshub_base_url: str | None
    default_digest_days: int
    # Kept for backward compatibility with older .env files.
    default_lookback_hours: int

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
            fetch_timeout_seconds=float(_env("FETCH_TIMEOUT_SECONDS", "20") or "20"),
            rsshub_base_url=_env("RSSHUB_BASE_URL"),
            default_digest_days=digest_days,
            default_lookback_hours=lookback_hours,
        )
