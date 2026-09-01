from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import httpx

from bot.fetchers.base import BaseFetcher, FetchError
from bot.http_util import HttpService
from bot.models import NewsItem, Source
from bot.summarize import clean_and_summarize, clean_text, first_meaningful_line


def normalize_rss_url(value: str) -> str:
    """Validate an HTTP(S) RSS feed URL and return its normalized form."""
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "Укажите RSS-адрес с http:// или https://, например "
            "https://example.com/feed/"
        )
    return url


def _entry_datetime(entry: feedparser.FeedParserDict) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


class RSSFetcher(BaseFetcher):
    """Fetch articles from an RSS or Atom feed."""

    source_type = "rss"

    def __init__(
        self, timeout: float = 20.0, http: HttpService | None = None
    ) -> None:
        self.timeout = timeout
        self.http = http

    async def fetch(
        self,
        source: Source,
        *,
        since: datetime | None = None,
        max_pages: int = 1,
    ) -> list[NewsItem]:
        del max_pages  # RSS feeds expose their own item window.
        url = normalize_rss_url(source.identifier)
        own_http = self.http is None
        http = self.http or HttpService(timeout=self.timeout)
        try:
            try:
                raw = await http.get_text(url)
            except httpx.HTTPError as exc:
                raise FetchError(f"Не удалось загрузить RSS: {url}") from exc
        finally:
            if own_http:
                await http.aclose()

        parsed = feedparser.parse(raw)
        if parsed.bozo and not parsed.entries:
            raise FetchError(f"RSS не распознан: {url}")
        if not parsed.entries:
            return []

        feed_title = clean_text(str(parsed.feed.get("title") or ""))
        items: list[NewsItem] = []
        seen: set[str] = set()
        for entry in parsed.entries:
            link = str(entry.get("link") or "").strip()
            external_id = str(entry.get("id") or link or "").strip()
            title = clean_text(str(entry.get("title") or ""))
            body = clean_text(
                str(entry.get("summary") or entry.get("description") or "")
            )[:2000]
            if not title:
                title = first_meaningful_line(body, max_len=240)
            if not title:
                continue
            published_at = _entry_datetime(entry)
            if since and published_at and published_at < since:
                continue
            key = external_id or title
            if key in seen:
                continue
            seen.add(key)
            items.append(
                NewsItem(
                    title=title,
                    url=link,
                    published_at=published_at,
                    source_type="rss",
                    source_name=source.title or feed_title or url,
                    summary=clean_and_summarize(
                        body or title, title=title, max_sentences=5, max_len=900
                    ),
                    body=body,
                    external_id=external_id or title,
                )
            )
        return sorted(
            items,
            key=lambda item: item.published_at
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
