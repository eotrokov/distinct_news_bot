from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from bot.config import Settings
from bot.db import Database
from bot.dedupe import deduplicate, fingerprint_for
from bot.fetchers import FetchError, TelegramChannelFetcher
from bot.models import NewsItem, Source, SourceType
from bot.topics import item_matches_topics

logger = logging.getLogger(__name__)


class DigestService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.fetchers = {
            "telegram": TelegramChannelFetcher(timeout=settings.fetch_timeout_seconds),
        }

    async def collect_for_user(self, user_id: int) -> tuple[list[NewsItem], list[str], list[str]]:
        """Return (items, errors, active_topics)."""
        sources = self.db.list_sources(user_id)
        if not sources:
            return [], ["Нет каналов. Добавьте через /add"], self.db.list_topics(user_id)

        topics = self.db.list_topics(user_id)

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

        # Topic filter (OR): empty topics → keep all.
        if topics:
            filtered = [
                item
                for item in filtered
                if item_matches_topics(item.title, item.summary, topics)
            ]

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
        return fresh[: self.settings.digest_limit], errors, topics

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
) -> list[str]:
    """Split digest into Telegram-safe message chunks (<= 4000 chars)."""
    topics = topics or []
    topic_note = ""
    if topics:
        topic_note = "Темы: " + ", ".join(topics) + "\n"

    chunks: list[str] = []
    if not items:
        text = "Новых новостей с прошлого запроса нет."
        if topics:
            text = (
                f"Новых новостей по темам ({', '.join(topics)}) "
                "с прошлого запроса нет."
            )
        if errors:
            text += "\n\nПроблемы с источниками:\n" + "\n".join(f"• {e}" for e in errors)
        return [text]

    header = f"Сводка: {len(items)} новостей без дублей\n{topic_note}"
    lines = [header]
    for idx, item in enumerate(items, start=1):
        when = ""
        if item.published_at:
            when = item.published_at.astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")
        link = f"\n{item.url}" if item.url else ""
        block = (
            f"\n{idx}. {item.source_name}\n"
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
    """Parse /add arguments into (type, identifier, title).

    Accepts:
      /add @channel
      /add channel
      /add telegram @channel [название]
      /add tg https://t.me/channel
    """
    if not args:
        raise ValueError(
            "Формат: /add @channel\n"
            "Несколько: /add @a @b\n"
            "Папка: /addlist https://t.me/addlist/…"
        )

    tokens = list(args)
    if tokens[0].lower() in {"telegram", "tg", "channel", "addlist", "folder", "list"}:
        tokens = tokens[1:]
    if not tokens:
        raise ValueError("Укажите канал: /add @channel")

    identifier = tokens[0].strip()
    title = " ".join(tokens[1:]).strip()
    if not title:
        handle = identifier.lstrip("@").split("/")[-1]
        title = f"@{handle}"
    return "telegram", identifier, title


def _default_title(_source_type: SourceType, identifier: str) -> str:
    handle = identifier.lstrip("@").split("/")[-1]
    return f"@{handle}"
