from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from bot.fetchers.base import BaseFetcher, FetchError
from bot.models import NewsItem, Source, SourceType
from bot.summarize import clean_and_summarize, strip_html


def parse_feed_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = parsedate_to_datetime(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


class RssFetcher(BaseFetcher):
    source_type = "rss"

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    async def fetch(self, source: Source) -> list[NewsItem]:
        return await self.fetch_url(
            source.identifier,
            source_type=source.source_type,
            source_name=source.title or source.identifier,
        )

    async def fetch_url(
        self,
        url: str,
        *,
        source_type: SourceType,
        source_name: str,
    ) -> list[NewsItem]:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": "distinct-news-bot/0.1"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
        except httpx.HTTPError as exc:
            raise FetchError(f"Не удалось загрузить RSS: {url}") from exc

        parsed = feedparser.parse(content)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise FetchError(f"Некорректный RSS: {url}")

        items: list[NewsItem] = []
        for entry in parsed.entries:
            title = (getattr(entry, "title", None) or "").strip()
            link = (getattr(entry, "link", None) or "").strip()
            if not title and not link:
                continue
            summary = (
                getattr(entry, "summary", None)
                or getattr(entry, "description", None)
                or ""
            )
            content_values = getattr(entry, "content", None) or []
            if not summary and content_values:
                summary = content_values[0].get("value", "") if isinstance(content_values[0], dict) else str(content_values[0])
            published = (
                parse_feed_datetime(getattr(entry, "published", None))
                or parse_feed_datetime(getattr(entry, "updated", None))
            )
            external_id = str(getattr(entry, "id", None) or link or title)
            raw_summary = strip_html(str(summary))
            items.append(
                NewsItem(
                    title=title or link,
                    url=link,
                    published_at=published,
                    source_type=source_type,
                    source_name=source_name,
                    summary=clean_and_summarize(raw_summary, title=title) or None,
                    external_id=external_id,
                )
            )
        return items
