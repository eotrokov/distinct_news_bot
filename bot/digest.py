from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from bot.config import Settings
from bot.db import Database
from bot.dedupe import deduplicate, fingerprint_for
from bot.fetchers import (
    FacebookFetcher,
    FetchError,
    RiaFetcher,
    RssFetcher,
    TelegramChannelFetcher,
    TwitterFetcher,
)
from bot.models import NewsItem, Source, SourceType

logger = logging.getLogger(__name__)


class DigestService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.rss = RssFetcher(timeout=settings.fetch_timeout_seconds)
        self.fetchers = {
            "rss": self.rss,
            "telegram": TelegramChannelFetcher(timeout=settings.fetch_timeout_seconds),
            "ria": RiaFetcher(self.rss),
            "facebook": FacebookFetcher(self.rss, settings.rsshub_base_url),
            "twitter": TwitterFetcher(self.rss, settings.rsshub_base_url),
        }

    async def collect_for_user(self, user_id: int) -> tuple[list[NewsItem], list[str]]:
        sources = self.db.list_sources(user_id)
        if not sources:
            return [], ["Нет источников. Добавьте через /add"]

        since = self.db.get_last_digest_at(user_id)
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(
                hours=self.settings.default_lookback_hours
            )

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

        # Keep only items newer than last digest (when date is known).
        filtered: list[NewsItem] = []
        for item in items:
            if item.published_at is None or item.published_at >= since:
                filtered.append(item)

        unique = deduplicate(filtered)

        # Drop items already shown to this user.
        fps = [fingerprint_for(item) for item in unique]
        unseen_fps = self.db.filter_unseen(user_id, fps)
        fresh = [item for item, fp in zip(unique, fps) if fp in unseen_fps]

        # Newest first, then truncate.
        fresh.sort(
            key=lambda i: i.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return fresh[: self.settings.digest_limit], errors

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


def format_digest(items: list[NewsItem], errors: list[str]) -> list[str]:
    """Split digest into Telegram-safe message chunks (<= 4000 chars)."""
    chunks: list[str] = []
    if not items:
        text = "Новых новостей с прошлого запроса нет."
        if errors:
            text += "\n\nПроблемы с источниками:\n" + "\n".join(f"• {e}" for e in errors)
        return [text]

    header = f"Сводка: {len(items)} новостей без дублей\n"
    lines = [header]
    for idx, item in enumerate(items, start=1):
        when = ""
        if item.published_at:
            when = item.published_at.astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")
        link = f"\n{item.url}" if item.url else ""
        block = (
            f"\n{idx}. [{item.source_type}] {item.source_name}\n"
            f"{item.title}"
            f"{link}"
            f"{f' ({when})' if when else ''}\n"
        )
        candidate = "".join(lines) + block
        if len(candidate) > 3800:
            chunks.append("".join(lines).rstrip())
            lines = [f"(продолжение)\n{block}"]
        else:
            lines.append(block)

    body = "".join(lines).rstrip()
    if errors:
        err_block = "\n\nПроблемы с источниками:\n" + "\n".join(f"• {e}" for e in errors)
        if len(body) + len(err_block) > 3900:
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
