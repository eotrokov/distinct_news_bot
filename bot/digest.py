from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from bot.ai_summarize import (
    ai_summary_active,
    enrich_items,
    merge_items_into_analysis,
)
from bot.analyzer import NewsAnalyzer, item_urls
from bot.config import Settings
from bot.db import Database
from bot.dedupe import fingerprint_for
from bot.fetchers import FetchError, TelegramChannelFetcher
from bot.http_util import HttpService
from bot.models import NewsItem, Source, SourceType
from bot.topics import item_matches_topics

logger = logging.getLogger(__name__)

LEGACY_SOURCE_TYPES = frozenset({"rss", "ria", "facebook", "twitter"})

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
        raise ValueError(
            "Формат: /news [дни] или /news new [дни]\n"
            "Примеры: /news 7, /news new"
        )
    days = int(raw)
    if days < MIN_DIGEST_DAYS or days > MAX_DIGEST_DAYS:
        raise ValueError(
            f"Число дней должно быть от {MIN_DIGEST_DAYS} до {MAX_DIGEST_DAYS}"
        )
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
    urls = item_urls(item)
    if not urls:
        return ""
    if len(urls) == 1:
        return f'<a href="{escape(urls[0], quote=True)}">источник</a>'
    parts = [
        f'<a href="{escape(url, quote=True)}">канал{idx}</a>'
        for idx, url in enumerate(urls, start=1)
    ]
    return ", ".join(parts)


def _format_digest_item(item: NewsItem) -> str:
    """SEO digest item: 2-sentence summary + source link (no numbering)."""
    essence = escape((item.summary or item.title or "").strip() or "Без заголовка")
    link = _format_item_links(item).strip()
    if link:
        return f"{essence}\n{link}"
    return essence


class DigestService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.analyzer = NewsAnalyzer()
        self.http = HttpService(
            timeout=settings.fetch_timeout_seconds,
            concurrency=settings.fetch_concurrency,
            cache_ttl_seconds=settings.fetch_cache_ttl_seconds,
        )
        self.fetchers = {
            "telegram": TelegramChannelFetcher(
                timeout=settings.fetch_timeout_seconds,
                http=self.http,
            ),
        }

    async def aclose(self) -> None:
        await self.http.aclose()

    async def collect_for_user(
        self,
        user_id: int,
        days: int | None = None,
        *,
        only_unseen: bool = False,
    ) -> tuple[list[NewsItem], list[str], list[str], int, dict[str, Any]]:
        """Return (items, errors, topics, days_used, analysis).

        Same ranking pipeline as weekly digests: time window, noise filter,
        merge duplicates, sort by reactions/views. When ``only_unseen`` is
        True, drop items already marked seen from prior digests.
        """
        days_used = clamp_digest_days(days, self.settings.default_digest_days)
        ent = self.db.get_entitlement(user_id)
        max_days = ent.limits().max_digest_days
        if days_used > max_days:
            days_used = max_days
        empty_analysis: dict[str, Any] = {
            "categories": {},
            "stats": {
                "total_processed": 0,
                "filtered_out": 0,
                "deduped_merged": 0,
                "final_count": 0,
                "period_days": days_used,
                "sort_by": "reactions",
                "only_unseen": only_unseen,
            },
        }
        sources = self.db.list_sources(user_id)
        topics = self.db.list_topics(user_id)
        if not sources:
            return (
                [],
                ["Нет каналов. Добавьте через /add или кнопку «Источники»"],
                topics,
                days_used,
                empty_analysis,
            )

        since = datetime.now(timezone.utc) - timedelta(days=days_used)
        # Public preview ~20 posts/page; longer windows paginate deeper, like weekly.
        max_pages = 5 if days_used >= 5 else 2

        results = await asyncio.gather(
            *[self._safe_fetch(source, since=since, max_pages=max_pages) for source in sources],
            return_exceptions=False,
        )

        items: list[NewsItem] = []
        errors: list[str] = []
        for source, result in zip(sources, results):
            fetched, err = result
            if err:
                errors.append(f"#{source.id} {source.title}: {err}")
            items.extend(fetched)

        filtered = [
            item
            for item in items
            if item.published_at is None or item.published_at >= since
        ]
        if topics:
            filtered = [
                item
                for item in filtered
                if item_matches_topics(item.title, item.summary or item.body, topics)
            ]

        analysis = self.analyzer.process(
            filtered,
            period=days_used,
            max_sentences=self.settings.summary_max_sentences,
        )
        flat: list[NewsItem] = []
        for cat_items in analysis["categories"].values():
            flat.extend(cat_items)

        if only_unseen and flat:
            fps = [fingerprint_for(item) for item in flat]
            unseen_fps = self.db.filter_unseen(user_id, fps)
            flat = [
                item
                for item, fp in zip(flat, fps)
                if fp in unseen_fps
            ]
            keep = {(it.url, it.title, it.external_id) for it in flat}
            analysis = {
                **analysis,
                "categories": {
                    name: [
                        it
                        for it in cat
                        if (it.url, it.title, it.external_id) in keep
                    ]
                    for name, cat in analysis["categories"].items()
                    if any((it.url, it.title, it.external_id) in keep for it in cat)
                },
                "stats": {
                    **analysis["stats"],
                    "final_count": len(flat),
                    "only_unseen": True,
                },
            }
        else:
            analysis = {
                **analysis,
                "stats": {**analysis["stats"], "only_unseen": only_unseen},
            }

        limited = flat[: self.settings.digest_limit]
        if len(flat) > len(limited):
            keep = {(it.url, it.title, it.external_id) for it in limited}
            analysis = {
                **analysis,
                "categories": {
                    name: [
                        it
                        for it in cat
                        if (it.url, it.title, it.external_id) in keep
                    ]
                    for name, cat in analysis["categories"].items()
                    if any((it.url, it.title, it.external_id) in keep for it in cat)
                },
                "stats": {**analysis["stats"], "final_count": len(limited)},
            }

        if ai_summary_active(self.settings) and limited:
            enriched = await enrich_items(limited, self.settings)
            analysis = merge_items_into_analysis(analysis, enriched)
            limited = enriched

        return limited, errors, topics, days_used, analysis

    async def _safe_fetch(
        self,
        source: Source,
        *,
        since: datetime | None = None,
        max_pages: int = 1,
    ) -> tuple[list[NewsItem], str | None]:
        fetcher = self.fetchers.get(source.source_type)
        if fetcher is None:
            if source.source_type in LEGACY_SOURCE_TYPES:
                return (
                    [],
                    "больше не поддерживается — удалите и добавьте Telegram-канал",
                )
            return [], f"неизвестный тип {source.source_type}"
        try:
            items = await fetcher.fetch(  # type: ignore[call-arg]
                source, since=since, max_pages=max_pages
            )
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
        return format_digest_result(
            result,
            period,
            errors=errors or [],
            topics=topics or [],
            page_size=self.settings.digest_page_size,
        )


def format_digest_result(
    result: dict[str, Any],
    period: int,
    *,
    errors: list[str] | None = None,
    topics: list[str] | None = None,
    page_size: int = 10,
) -> list[str]:
    """Build digest pages: at most ``page_size`` news items per page."""
    errors = errors or []
    topics = topics or []
    days_used = int(period) if period else 3
    stats = result.get("stats") or {}
    categories = result.get("categories") or {}

    flat: list[tuple[str, NewsItem]] = []
    for cat_name, cat_items in categories.items():
        for item in cat_items:
            flat.append((cat_name, item))

    if not flat:
        only_unseen = bool(stats.get("only_unseen"))
        if only_unseen:
            text = (
                f"За последние {days_used} {_days_word(days_used)} "
                "нового нет — всё уже было в прошлых сводках.\n"
                "Нажмите «Сводка» для топа за период или /reset, "
                "чтобы снова показывать просмотренное."
            )
        else:
            text = f"За последние {days_used} {_days_word(days_used)} новых постов нет."
        if topics:
            text = (
                f"За последние {days_used} {_days_word(days_used)} нет постов "
                f"по темам ({', '.join(topics)})."
            )
        if errors:
            text += "\n\nПроблемы с источниками:\n" + "\n".join(
                f"• {e}" for e in errors
            )
        return [text]

    only_unseen = bool(stats.get("only_unseen"))
    if only_unseen:
        header = (
            f"🆕 SEO-дайджест: только новое за {days_used} {_days_word(days_used)}"
        )
    else:
        header = (
            f"🔥 SEO-дайджест за {days_used} {_days_word(days_used)} (по реакциям)"
        )
    if topics:
        header += f"\nТемы: {', '.join(topics)}"

    stats_line = (
        f"\n\n📊 Обработано: {stats.get('total_processed', len(flat))}, "
        f"в дайджест: {stats.get('final_count', len(flat))}, "
        f"отсеяно (реклама/оффтоп): {stats.get('filtered_out', 0)}, "
        f"дублей объединено: {stats.get('deduped_merged', 0)}."
    )
    err_block = ""
    if errors:
        err_block = "\n\nПроблемы с источниками:\n" + "\n".join(
            f"• {e}" for e in errors
        )

    page_size = max(1, int(page_size))
    pages: list[str] = []
    total_items = len(flat)

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
                parts.append(f"\n\n<b>{escape(cat_name)}</b>\n")
                last_cat = cat_name
            else:
                parts.append("\n\n")
            parts.append(_format_digest_item(item))

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
        "categories": {"🔍 Google и Поиск": list(items)} if items else {},
        "stats": {
            "total_processed": len(items),
            "final_count": len(items),
            "filtered_out": 0,
            "deduped_merged": 0,
            "sort_by": "reactions",
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
    """Parse /add arguments into (type, identifier, title). Telegram only."""
    if not args:
        raise ValueError(
            "Формат: /add @channel [название]\n"
            "Несколько каналов: /add telegram @a @b\n"
            "Папка: /addlist https://t.me/addlist/…"
        )

    removed = {"rss", "ria", "facebook", "twitter", "fb", "x", "tw", "twitter/x"}
    aliases = {
        "tg": "telegram",
        "channel": "telegram",
        "addlist": "telegram",
        "folder": "telegram",
        "list": "telegram",
    }
    raw_type = args[0].lower().strip()
    if raw_type in removed:
        raise ValueError(
            "Сейчас поддерживаются только публичные Telegram-каналы.\n"
            "Пример: /add @bbcnews или /add telegram @ch1 @ch2"
        )

    if raw_type == "telegram" or raw_type in aliases:
        if len(args) < 2:
            raise ValueError(
                "Формат: /add telegram @channel [название]\n"
                "Папка каналов: /addlist https://t.me/addlist/…"
            )
        identifier = args[1].strip()
        title = " ".join(args[2:]).strip() if len(args) > 2 else ""
    else:
        # Bare @channel / t.me/… without an explicit type keyword.
        identifier = args[0].strip()
        title = " ".join(args[1:]).strip() if len(args) > 1 else ""

    if not title:
        title = _default_title("telegram", identifier)
    return "telegram", identifier, title


def _default_title(source_type: SourceType, identifier: str) -> str:
    handle = identifier.lstrip("@").split("/")[-1]
    return f"@{handle}"
