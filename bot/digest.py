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
from bot.builtin_sources import merge_sources
from bot.config import Settings
from bot.db import Database
from bot.dedupe import fingerprint_for
from bot.fetchers import (
    FetchError,
    RssFetcher,
    TelegramChannelFetcher,
    looks_like_rss_url,
    rss_title_from_url,
)
from bot.http_util import HttpService
from bot.models import NewsItem, Source, SourceType
from bot.topics import item_matches_topics

logger = logging.getLogger(__name__)

LEGACY_SOURCE_TYPES = frozenset({"ria", "facebook", "twitter"})

MIN_DIGEST_DAYS = 1
MAX_DIGEST_DAYS = 30
FLASH_DIGEST_LIMIT = 5
FLASH_MODE_ALIASES = frozenset(
    {"flash", "express", "экспресс", "fast", "top5", "пульс"}
)


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
            "Формат: /news [дни], /news new [дни] или /news flash [дни]\n"
            "Примеры: /news 7, /news new, /news flash"
        )
    days = int(raw)
    if days < MIN_DIGEST_DAYS or days > MAX_DIGEST_DAYS:
        raise ValueError(
            f"Число дней должно быть от {MIN_DIGEST_DAYS} до {MAX_DIGEST_DAYS}"
        )
    return days


def pop_flash_flag(args: list[str]) -> tuple[list[str], bool]:
    """Pull flash/express mode token from `/news` args if present."""
    if not args:
        return args, False
    token = args[0].strip().lower()
    if token in FLASH_MODE_ALIASES:
        return args[1:], True
    return args, False


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


def _short_category_label(cat_name: str) -> str:
    """Drop leading emoji from category titles for compact pulse lines."""
    parts = cat_name.strip().split(maxsplit=1)
    if len(parts) == 2 and not parts[0].isalnum():
        return parts[1]
    return cat_name.strip()


def _category_heat(
    categories: dict[str, list[NewsItem]],
) -> list[tuple[str, int, int]]:
    """Return (category, reactions_sum, item_count) sorted by heat."""
    scored: list[tuple[str, int, int]] = []
    for cat_name, cat_items in categories.items():
        if not cat_items:
            continue
        reactions = sum(int(item.reactions or 0) for item in cat_items)
        scored.append((cat_name, reactions, len(cat_items)))
    scored.sort(key=lambda row: (row[1], row[2]), reverse=True)
    return scored


def digest_pulse_line(categories: dict[str, list[NewsItem]]) -> str:
    """One-line 'what's hot' blurb from category reaction heat."""
    heat = _category_heat(categories)
    if not heat:
        return ""
    hot = [_short_category_label(name) for name, _, _ in heat[:2]]
    quiet = [
        _short_category_label(name)
        for name, reactions, _ in heat[2:]
        if reactions == 0
    ][:1]
    parts = [f"🔥 {', '.join(hot)}"]
    if quiet:
        parts.append(f"💤 {quiet[0]}")
    elif len(heat) >= 3:
        parts.append(f"· {_short_category_label(heat[2][0])}")
    return "Пульс: " + " ".join(parts)


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


def _format_engagement(item: NewsItem) -> str:
    reactions = int(item.reactions or 0)
    views = int(item.views or 0)
    bits: list[str] = []
    if reactions > 0:
        bits.append(f"🔥 {reactions}")
    if views > 0:
        bits.append(f"👁 {views}")
    return " · ".join(bits)


def _format_digest_item(item: NewsItem, *, show_engagement: bool = False) -> str:
    """SEO digest item: 2-sentence summary + source link (no numbering)."""
    essence = escape((item.summary or item.title or "").strip() or "Без заголовка")
    link = _format_item_links(item).strip()
    engagement = _format_engagement(item) if show_engagement else ""
    meta_parts = [p for p in (engagement, link) if p]
    if meta_parts:
        return f"{essence}\n{' · '.join(meta_parts)}"
    return essence


def _empty_digest_pages(
    *,
    days_used: int,
    topics: list[str],
    errors: list[str],
    only_unseen: bool,
    flash: bool,
) -> list[str]:
    if flash:
        text = (
            f"⚡ Экспресс: за последние {days_used} {_days_word(days_used)} "
            "горячих постов нет."
        )
    elif only_unseen:
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
        text += "\n\nПроблемы с источниками:\n" + "\n".join(f"• {e}" for e in errors)
    return [text]


def _flatten_ranked(
    categories: dict[str, list[NewsItem]],
) -> list[tuple[str, NewsItem]]:
    flat: list[tuple[str, NewsItem]] = []
    for cat_name, cat_items in categories.items():
        for item in cat_items:
            flat.append((cat_name, item))
    flat.sort(
        key=lambda row: (
            int(row[1].reactions or 0),
            int(row[1].views or 0),
            row[1].published_at.timestamp() if row[1].published_at else 0.0,
        ),
        reverse=True,
    )
    return flat


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
            "rss": RssFetcher(
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
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[NewsItem], list[str], list[str], int, dict[str, Any]]:
        """Return (items, errors, topics, days_used, analysis).

        Same ranking pipeline as weekly digests: time window, noise filter,
        merge duplicates, sort by reactions/views. When ``only_unseen`` is
        True, drop items already marked seen from prior digests.

        Optional ``since`` / ``until`` (UTC-aware) override the rolling
        ``days`` window — used for scheduled digests of the previous
        calendar day.
        """
        days_used = clamp_digest_days(days, self.settings.default_digest_days)
        if since is not None and until is not None and until > since:
            span = until - since
            days_used = clamp_digest_days(
                max(1, int(round(span.total_seconds() / 86400))),
                self.settings.default_digest_days,
            )
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
        sources = merge_sources(self.db.list_sources(user_id))
        topics = self.db.list_topics(user_id)
        if not sources:
            return (
                [],
                [
                    "Нет источников. Добавьте канал /add @channel "
                    "или RSS /add rss https://site.com/feed/"
                ],
                topics,
                days_used,
                empty_analysis,
            )

        window_since = since or (
            datetime.now(timezone.utc) - timedelta(days=days_used)
        )
        window_until = until
        # Public preview ~20 posts/page; longer windows paginate deeper, like weekly.
        max_pages = 5 if days_used >= 5 else 2

        results = await asyncio.gather(
            *[
                self._safe_fetch(source, since=window_since, max_pages=max_pages)
                for source in sources
            ],
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
            if item.published_at is None or item.published_at >= window_since
        ]
        if window_until is not None:
            filtered = [
                item
                for item in filtered
                if item.published_at is None or item.published_at < window_until
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

    def mark_digest_delivered(
        self,
        user_id: int,
        items: list[NewsItem],
        *,
        trigger: str = "manual",
    ) -> None:
        now = datetime.now(timezone.utc)
        fingerprints = [
            (fingerprint_for(item), item.url, item.title) for item in items
        ]
        self.db.mark_seen(user_id, fingerprints)
        self.db.set_last_digest_at(user_id, now)
        self.db.log_digest_event(user_id, len(items), trigger=trigger)
        self.db.cleanup_seen(user_id)

    def format_digest(
        self,
        result: dict[str, Any],
        period: int,
        *,
        errors: list[str] | None = None,
        topics: list[str] | None = None,
        flash: bool = False,
    ) -> list[str]:
        return format_digest_result(
            result,
            period,
            errors=errors or [],
            topics=topics or [],
            page_size=self.settings.digest_page_size,
            flash=flash,
        )


def format_digest_result(
    result: dict[str, Any],
    period: int,
    *,
    errors: list[str] | None = None,
    topics: list[str] | None = None,
    page_size: int = 10,
    flash: bool = False,
    flash_limit: int = FLASH_DIGEST_LIMIT,
) -> list[str]:
    """Build digest pages: at most ``page_size`` news items per page.

    When ``flash`` is True, return a single compact page with the global
    top-N hottest items (by reactions) and a category pulse line.
    """
    errors = errors or []
    topics = topics or []
    days_used = int(period) if period else 3
    stats = result.get("stats") or {}
    categories = result.get("categories") or {}
    only_unseen = bool(stats.get("only_unseen"))

    flat = _flatten_ranked(categories) if flash else [
        (cat_name, item)
        for cat_name, cat_items in categories.items()
        for item in cat_items
    ]

    if not flat:
        return _empty_digest_pages(
            days_used=days_used,
            topics=topics,
            errors=errors,
            only_unseen=only_unseen,
            flash=flash,
        )

    pulse = digest_pulse_line(categories)
    if flash:
        limit = max(1, int(flash_limit))
        top = flat[:limit]
        header = (
            f"⚡ Экспресс: топ-{len(top)} за {days_used} {_days_word(days_used)}"
        )
        if topics:
            header += f"\nТемы: {', '.join(topics)}"
        parts: list[str] = [header]
        if pulse:
            parts.append(f"\n{escape(pulse)}")
        for idx, (cat_name, item) in enumerate(top, start=1):
            cat_label = escape(_short_category_label(cat_name))
            parts.append(f"\n\n<b>{idx}.</b> <i>{cat_label}</i>\n")
            parts.append(_format_digest_item(item, show_engagement=True))
        stats_line = (
            f"\n\n📊 Из {stats.get('final_count', len(flat))} в сводке — "
            f"только самый горячий топ. Полная: /news"
        )
        parts.append(stats_line)
        if errors:
            parts.append(
                "\n\nПроблемы с источниками:\n"
                + "\n".join(f"• {e}" for e in errors)
            )
        return ["".join(parts).rstrip()]

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
    if pulse:
        header += f"\n{escape(pulse)}"

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
        parts = [header]
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
    flash: bool = False,
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
        flash=flash,
    )


def parse_add_args(args: list[str]) -> tuple[SourceType, str, str]:
    """Parse /add arguments into (type, identifier, title)."""
    if not args:
        raise ValueError(
            "Формат: /add @channel [название]\n"
            "Несколько каналов: /add telegram @a @b\n"
            "RSS: /add rss https://site.com/feed/ [название]\n"
            "Папка: /addlist https://t.me/addlist/…"
        )

    removed = {"ria", "facebook", "twitter", "fb", "x", "tw", "twitter/x"}
    aliases = {
        "tg": "telegram",
        "channel": "telegram",
        "addlist": "telegram",
        "folder": "telegram",
        "list": "telegram",
    }
    rss_aliases = {"rss", "feed", "atom", "blog"}
    raw_type = args[0].lower().strip()
    if raw_type in removed:
        raise ValueError(
            "Поддерживаются публичные Telegram-каналы и RSS-фиды.\n"
            "Примеры: /add @bbcnews или /add rss https://ahrefs.com/blog/feed/"
        )

    if raw_type in rss_aliases:
        if len(args) < 2:
            raise ValueError(
                "Формат: /add rss https://site.com/feed/ [название]"
            )
        identifier = args[1].strip()
        title = " ".join(args[2:]).strip() if len(args) > 2 else ""
        if not title:
            title = _default_title("rss", identifier)
        return "rss", identifier, title

    if raw_type == "telegram" or raw_type in aliases:
        if len(args) < 2:
            raise ValueError(
                "Формат: /add telegram @channel [название]\n"
                "Папка каналов: /addlist https://t.me/addlist/…"
            )
        identifier = args[1].strip()
        title = " ".join(args[2:]).strip() if len(args) > 2 else ""
        if not title:
            title = _default_title("telegram", identifier)
        return "telegram", identifier, title

    identifier = args[0].strip()
    title = " ".join(args[1:]).strip() if len(args) > 1 else ""
    if looks_like_rss_url(identifier):
        if not title:
            title = _default_title("rss", identifier)
        return "rss", identifier, title
    if not title:
        title = _default_title("telegram", identifier)
    return "telegram", identifier, title


def _default_title(source_type: SourceType, identifier: str) -> str:
    if source_type == "rss":
        return rss_title_from_url(identifier)
    handle = identifier.lstrip("@").split("/")[-1]
    return f"@{handle}"
