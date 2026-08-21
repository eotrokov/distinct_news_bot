from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from bot.analyzer import NewsAnalyzer
from bot.config import Settings
from bot.db import Database
from bot.dedupe import fingerprint_for
from bot.excerpt import format_item_block
from bot.fetchers import (
    FacebookFetcher,
    FetchError,
    RiaFetcher,
    RssFetcher,
    TelegramChannelFetcher,
    TwitterFetcher,
)
from bot.models import NewsItem, Source, SourceType
from bot.topics import item_matches_topics

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
    return int(raw)


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
    ) -> tuple[list[NewsItem], list[str], list[str], int, dict[str, Any]]:
        """Return (items, errors, topics, days_used, analysis)."""
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
        if not sources:
            return (
                [],
                ["Нет источников. Добавьте через /add"],
                self.db.list_topics(user_id),
                days_used,
                empty_analysis,
            )

        topics = self.db.list_topics(user_id)
        since = datetime.now(timezone.utc) - timedelta(days=days_used)

        results = await asyncio.gather(
            *[self._safe_fetch(source) for source in sources],
            return_exceptions=False,
        )

        items: list[NewsItem] = []
        errors: list[str] = []
        for source, result in zip(sources, results):
            fetched, err = result
            if err:
                errors.append(f"#{source.id} {source.title}: {err}")
            items.extend(fetched)

        filtered: list[NewsItem] = []
        for item in items:
            if item.published_at is None or item.published_at >= since:
                filtered.append(item)

        if topics:
            filtered = [
                item
                for item in filtered
                if item_matches_topics(item.title, item.summary or "", topics)
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
        return limited, errors, topics, days_used, analysis

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
    items: list[NewsItem],
    errors: list[str],
    topics: list[str] | None = None,
    days: int | None = None,
    analysis: dict[str, Any] | None = None,
) -> list[str]:
    """Build a categorized «портянка» of analyzed post excerpts."""
    topics = topics or []
    topic_note = ""
    if topics:
        topic_note = "Фильтр тем: " + ", ".join(topics) + "\n"
    days_note = f"Период: последние {days} дн.\n" if days else ""

    stats = (analysis or {}).get("stats") or {}
    stats_note = ""
    if stats:
        stats_note = (
            f"Обработано: {stats.get('total_processed', 0)}, "
            f"шум: −{stats.get('filtered_out', 0)}, "
            f"слияний: {stats.get('deduped_merged', 0)}\n"
        )

    chunks: list[str] = []
    if not items:
        text = "За выбранный период новых постов нет."
        if days:
            text = f"За последние {days} дн. новых постов нет."
        if topics:
            text = f"За период нет постов по темам ({', '.join(topics)})."
        if errors:
            text += "\n\nПроблемы с источниками:\n" + "\n".join(f"• {e}" for e in errors)
        return [text]

    header = (
        f"Выжимка: {len(items)} постов из ваших источников\n"
        f"{days_note}"
        f"{stats_note}"
        f"(дубли и рекламный шум убраны)\n"
        f"{topic_note}"
        f"Листайте ленту — по ссылке можно открыть оригинал.\n"
    )
    lines = [header]

    categories = (analysis or {}).get("categories") or {}
    if categories:
        global_idx = 1
        for cat_name, cat_items in categories.items():
            block_cat = f"\n<b>📁 {cat_name}</b>\n"
            candidate = "".join(lines) + block_cat
            if len(candidate) > 3700:
                chunks.append("".join(lines).rstrip())
                lines = [f"<i>продолжение</i>\n{block_cat}"]
            else:
                lines.append(block_cat)
            for item in cat_items:
                block = "\n" + format_item_block(global_idx, item)
                global_idx += 1
                candidate = "".join(lines) + block
                if len(candidate) > 3700:
                    chunks.append("".join(lines).rstrip())
                    lines = [f"<i>продолжение</i>\n{block}"]
                else:
                    lines.append(block)
    else:
        for idx, item in enumerate(items, start=1):
            block = "\n" + format_item_block(idx, item)
            candidate = "".join(lines) + block
            if len(candidate) > 3700:
                chunks.append("".join(lines).rstrip())
                lines = [f"<i>продолжение</i>\n{block}"]
            else:
                lines.append(block)

    body = "".join(lines).rstrip()
    if errors:
        err_block = "\n\nПроблемы с источниками:\n" + "\n".join(f"• {e}" for e in errors)
        if len(body) + len(err_block) > 3800:
            chunks.append(body)
            chunks.append(err_block.strip())
        else:
            body += err_block
            chunks.append(body)
    else:
        chunks.append(body)
    return chunks


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
