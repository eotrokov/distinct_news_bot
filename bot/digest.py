from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from bot.analyzer import NewsAnalyzer, item_urls
from bot.config import Settings
from bot.db import Database
from bot.dedupe import fingerprint_for
from bot.fetchers import (
    FacebookFetcher,
    FetchError,
    RiaFetcher,
    RssFetcher,
    TelegramChannelFetcher,
    TwitterFetcher,
)
from bot.models import NewsItem, Source, SourceType
from bot.topics import item_passes_topic_filters

logger = logging.getLogger(__name__)

MIN_DIGEST_DAYS = 1
MAX_DIGEST_DAYS = 30


def clamp_digest_days(days: int | None, default: int) -> int:
    if days is None:
        return max(MIN_DIGEST_DAYS, min(MAX_DIGEST_DAYS, default))
    return max(MIN_DIGEST_DAYS, min(MAX_DIGEST_DAYS, int(days)))


def parse_days_arg(args: list[str] | None) -> int | None:
    """Parse `/news 5` style argument. None → use settings default."""
    if not args:
        return None
    raw = args[0].strip().lower().rstrip("dд")
    if not raw.isdigit():
        raise ValueError("Формат: /news [дни], например /news 5 (1–30)")
    days = int(raw)
    if days < MIN_DIGEST_DAYS or days > MAX_DIGEST_DAYS:
        raise ValueError(f"Число дней должно быть от {MIN_DIGEST_DAYS} до {MAX_DIGEST_DAYS}")
    return days


def _days_word(days: int) -> str:
    n = abs(int(days)) % 100
    n1 = n % 10
    if 11 <= n <= 14:
        return "дней"
    if n1 == 1:
        return "день"
    if 2 <= n1 <= 4:
        return "дня"
    return "дней"


def _format_item_links(item: NewsItem) -> str:
    from html import escape

    urls = item_urls(item)
    if not urls:
        return ""
    if len(urls) == 1:
        return f' <a href="{escape(urls[0], quote=True)}">источник</a>'
    parts = [
        f'<a href="{escape(url, quote=True)}">канал{idx}</a>'
        for idx, url in enumerate(urls, start=1)
    ]
    return " " + ", ".join(parts)


def _format_digest_item(idx: int, item: NewsItem) -> str:
    from html import escape

    essence = escape((item.summary or item.title or "").strip() or "Без заголовка")
    return f"{idx}. <b>{essence}</b>{_format_item_links(item)}"


class DigestService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.analyzer = NewsAnalyzer()
        self.rss = RssFetcher(timeout=settings.fetch_timeout_seconds)
        self.fetchers = {
            "rss": self.rss,
            "telegram": TelegramChannelFetcher(timeout=settings.fetch_timeout_seconds),
            "ria": RiaFetcher(self.rss),
            "facebook": FacebookFetcher(self.rss, settings.rsshub_base_url),
            "twitter": TwitterFetcher(self.rss, settings.rsshub_base_url),
        }

    async def collect_for_user(
        self,
        user_id: int,
        days: int | None = None,
    ) -> tuple[list[NewsItem], list[str], dict[str, list[str]], int, dict[str, Any]]:
        """Return (items, errors, topic_filters, days_used, analysis)."""
        days_used = clamp_digest_days(days, self.settings.default_digest_days)
        empty_analysis: dict[str, Any] = {
            "categories": {},
            "stats": {
                "total_processed": 0,
                "filtered_out": 0,
                "deduped_merged": 0,
                "final_count": 0,
                "period_days": days_used,
            },
        }
        sources = self.db.list_sources(user_id)
        include_topics = self.db.list_include_topics(user_id)
        exclude_topics = self.db.list_exclude_topics(user_id)
        topic_meta = {"include": include_topics, "exclude": exclude_topics}
        if not sources:
            return (
                [],
                ["Нет источников. Добавьте через /add"],
                topic_meta,
                days_used,
                empty_analysis,
            )

        active, paused = self.db.list_active_sources(
            user_id, self.settings.free_source_limit
        )
        sources = active
        since = datetime.now(timezone.utc) - timedelta(days=days_used)

        results = await asyncio.gather(
            *[self._safe_fetch(source) for source in sources],
            return_exceptions=False,
        )

        items: list[NewsItem] = []
        errors: list[str] = []
        if paused:
            errors.append(
                f"На паузе из‑за лимита слотов: {len(paused)} ист. "
                f"(бесплатно {self.settings.free_source_limit}, "
                f"далее {self.settings.stars_per_extra_source}⭐/канал/мес.)"
            )
        for source, result in zip(sources, results):
            fetched, err = result
            if err:
                errors.append(f"#{source.id} {source.title}: {err}")
            items.extend(fetched)

        filtered: list[NewsItem] = []
        for item in items:
            if item.published_at is None or item.published_at >= since:
                filtered.append(item)

        filtered = [
            item
            for item in filtered
            if item_passes_topic_filters(
                item.title,
                item.summary or "",
                include=include_topics,
                exclude=exclude_topics,
            )
        ]

        analysis = self.analyzer.process(filtered, period=days_used)
        flat: list[NewsItem] = []
        for cat_items in analysis["categories"].values():
            flat.extend(cat_items)

        limited = flat[: self.settings.digest_limit]
        # Keep categories aligned with the truncated list.
        if len(flat) > len(limited):
            keep = set(id(x) for x in limited)
            analysis = {
                **analysis,
                "categories": {
                    name: [it for it in cat if id(it) in keep]
                    for name, cat in analysis["categories"].items()
                    if any(id(it) in keep for it in cat)
                },
                "stats": {
                    **analysis["stats"],
                    "final_count": len(limited),
                },
            }
        return limited, errors, topic_meta, days_used, analysis

    async def _safe_fetch(self, source: Source) -> tuple[list[NewsItem], str | None]:
        fetcher = self.fetchers.get(source.source_type)
        if fetcher is None:
            return [], f"неизвестный тип {source.source_type}"
        try:
            items = await fetcher.fetch(source)
            return items, None
        except (FetchError, ValueError) as exc:
            logger.warning("Fetch failed for source %s: %s", source.id, exc)
            return [], str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected fetch error for source %s", source.id)
            return [], f"ошибка: {exc}"

    def mark_digest_delivered(self, user_id: int, items: list[NewsItem]) -> None:
        now = datetime.now(timezone.utc)
        fingerprints = [
            (fingerprint_for(item), item.url, item.title) for item in items
        ]
        self.db.mark_seen(user_id, fingerprints)
        self.db.set_last_digest_at(user_id, now)
        self.db.cleanup_seen(user_id)

    def format_digest(
        self,
        result: dict[str, Any],
        period: int,
        *,
        errors: list[str] | None = None,
        topics: list[str] | None = None,
    ) -> list[str]:
        """Format analyzer process() result into Telegram HTML pages."""
        return format_digest_result(
            result,
            period,
            errors=errors or [],
            topics=topics or [],
            page_size=self.settings.digest_page_size,
        )


def _topic_filter_note(topics: list[str] | dict[str, list[str]] | None) -> str:
    include, exclude = _split_topic_filters(topics)
    parts: list[str] = []
    if include:
        parts.append("показывать: " + ", ".join(include))
    if exclude:
        parts.append("скрывать: " + ", ".join(exclude))
    return "; ".join(parts)


def _split_topic_filters(
    topics: list[str] | dict[str, list[str]] | None,
) -> tuple[list[str], list[str]]:
    if not topics:
        return [], []
    if isinstance(topics, dict):
        return list(topics.get("include") or []), list(topics.get("exclude") or [])
    # Backward compat: plain list = include-only.
    return list(topics), []


def format_digest_result(
    result: dict[str, Any],
    period: int,
    *,
    errors: list[str] | None = None,
    topics: list[str] | dict[str, list[str]] | None = None,
    page_size: int = 10,
) -> list[str]:
    """Build digest pages: at most ``page_size`` news items per page."""
    errors = errors or []
    include_topics, exclude_topics = _split_topic_filters(topics)
    days_used = int(period) if period else 3
    stats = result.get("stats") or {}
    categories = result.get("categories") or {}

    # Flatten preserving category order: list of (category, item).
    flat: list[tuple[str, NewsItem]] = []
    for cat_name, cat_items in categories.items():
        for item in cat_items:
            flat.append((cat_name, item))

    if not flat:
        text = f"За последние {days_used} {_days_word(days_used)} новых постов нет."
        note = _topic_filter_note(topics)
        if note:
            text = (
                f"За последние {days_used} {_days_word(days_used)} нет постов "
                f"по фильтру ({note})."
            )
        if errors:
            text += "\n\nПроблемы с источниками:\n" + "\n".join(f"• {e}" for e in errors)
        return [text]

    header = (
        f"📰 Дайджест новостей SEO за последние {days_used} {_days_word(days_used)}"
    )
    note = _topic_filter_note(topics)
    if note:
        header += f"\nФильтр тем: {note}"

    stats_line = (
        f"\n\n📊 Обработано постов: {stats.get('total_processed', len(flat))}, "
        f"в дайджест вошло: {stats.get('final_count', len(flat))}, "
        f"отсеяно как реклама/оффтоп: {stats.get('filtered_out', 0)}, "
        f"объединено дублей: {stats.get('deduped_merged', 0)}."
    )
    err_block = ""
    if errors:
        err_block = "\n\nПроблемы с источниками:\n" + "\n".join(f"• {e}" for e in errors)

    page_size = max(1, int(page_size))
    pages: list[str] = []
    total_items = len(flat)
    global_idx = 1

    for start in range(0, total_items, page_size):
        chunk = flat[start : start + page_size]
        page_no = start // page_size + 1
        total_pages = (total_items + page_size - 1) // page_size
        parts: list[str] = [header]
        if total_pages > 1:
            parts.append(f"\n<i>Страница {page_no}/{total_pages}</i>")

        last_cat: str | None = None
        for cat_name, item in chunk:
            if cat_name != last_cat:
                parts.append(f"\n\n{cat_name}")
                last_cat = cat_name
            parts.append("\n" + _format_digest_item(global_idx, item))
            global_idx += 1

        is_last = start + page_size >= total_items
        if is_last:
            parts.append(stats_line)
            if err_block:
                parts.append(err_block)
        pages.append("".join(parts).rstrip())

    return pages


def format_digest(
    items: list[NewsItem],
    errors: list[str],
    topics: list[str] | None = None,
    days: int | None = None,
    analysis: dict[str, Any] | None = None,
    page_size: int = 10,
) -> list[str]:
    """Compatibility wrapper used by handlers/tests."""
    analysis = analysis or {
        "categories": {"📰 Новости": list(items)} if items else {},
        "stats": {
            "total_processed": len(items),
            "final_count": len(items),
            "filtered_out": 0,
            "deduped_merged": 0,
        },
    }
    return format_digest_result(
        analysis,
        days or 3,
        errors=errors,
        topics=topics or [],
        page_size=page_size,
    )


def parse_add_args(args: list[str]) -> tuple[SourceType, str, str]:
    """Parse /add arguments into (type, identifier, title)."""
    if len(args) < 2:
        raise ValueError(
            "Формат: /add <telegram|rss|ria|facebook|twitter> <id_или_url> [название]"
        )
    raw_type = args[0].lower().strip()
    aliases = {
        "tg": "telegram",
        "channel": "telegram",
        "fb": "facebook",
        "x": "twitter",
        "tw": "twitter",
        "twitter/x": "twitter",
    }
    source_type = aliases.get(raw_type, raw_type)
    if source_type not in {"telegram", "rss", "ria", "facebook", "twitter"}:
        raise ValueError(
            "Тип источника: telegram, rss, ria, facebook, twitter"
        )
    identifier = args[1].strip()
    title = " ".join(args[2:]).strip() if len(args) > 2 else ""
    if not title:
        title = _default_title(source_type, identifier)  # type: ignore[arg-type]
    return source_type, identifier, title  # type: ignore[return-value]


def _default_title(source_type: SourceType, identifier: str) -> str:
    if source_type == "telegram":
        handle = identifier.lstrip("@").split("/")[-1]
        return f"@{handle}"
    if source_type == "ria":
        return f"РИА ({identifier})"
    if source_type == "twitter":
        return f"@{identifier.lstrip('@')}"
    if source_type == "facebook":
        return f"FB:{identifier}"
    return identifier[:60]
