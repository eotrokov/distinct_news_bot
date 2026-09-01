from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone
from time import struct_time

import feedparser
import httpx
from bs4 import BeautifulSoup

from bot.fetchers.base import BaseFetcher, FetchError
from bot.http_util import HttpService
from bot.models import NewsItem, Source
from bot.summarize import clean_and_summarize, clean_text, first_meaningful_line

logger = logging.getLogger(__name__)


def _struct_time_to_datetime(t: struct_time | None) -> datetime | None:
    if not t:
        return None
    try:
        ts = calendar.timegm(t)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _clean_html_content(raw_html: str) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "lxml")
    return soup.get_text("\n", strip=True)


class RssFeedFetcher(BaseFetcher):
    """Fetch RSS/Atom feeds using feedparser and HttpService."""

    source_type = "rss"

    def __init__(
        self,
        timeout: float = 20.0,
        http: HttpService | None = None,
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
        feed_url = source.identifier.strip()
        if not feed_url.startswith(("http://", "https://")):
            feed_url = f"https://{feed_url}"

        own_http = self.http is None
        http = self.http or HttpService(timeout=self.timeout)
        try:
            try:
                xml_text = await http.get_text(feed_url)
            except httpx.HTTPError as exc:
                raise FetchError(f"Не удалось загрузить RSS-ленту: {source.title or feed_url}") from exc
        finally:
            if own_http:
                await http.aclose()

        parsed = feedparser.parse(xml_text)
        if parsed.bozo and not parsed.entries:
            err_msg = str(parsed.bozo_exception) if hasattr(parsed, "bozo_exception") else "некорректный XML/RSS"
            raise FetchError(f"Ошибка парсинга RSS {source.title or feed_url}: {err_msg}")

        items: list[NewsItem] = []
        for entry in parsed.entries:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()
            entry_id = getattr(entry, "id", "") or link or title

            published_at = _struct_time_to_datetime(
                getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
            )

            if since and published_at and published_at < since:
                continue

            # Extract content/description
            content = ""
            if hasattr(entry, "content") and entry.content:
                content = _clean_html_content(entry.content[0].get("value", ""))
            elif hasattr(entry, "summary"):
                content = _clean_html_content(entry.summary)
            elif hasattr(entry, "description"):
                content = _clean_html_content(entry.description)

            if not content and not title:
                continue

            cleaned_title = clean_text(title) or first_meaningful_line(content, max_len=240)
            body = clean_text(content or title)[:2000]
            summary_text = clean_and_summarize(
                content or title,
                title=cleaned_title,
                max_sentences=5,
                max_len=900,
            )

            items.append(
                NewsItem(
                    title=cleaned_title or "Без заголовка",
                    url=link,
                    published_at=published_at,
                    source_type="rss",
                    source_name=source.title or parsed.feed.get("title", "") or "RSS",
                    summary=summary_text,
                    body=body,
                    external_id=entry_id,
                    reactions=0,
                    views=0,
                )
            )

        seen: set[str] = set()
        unique: list[NewsItem] = []
        for item in sorted(
            items,
            key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        ):
            key = item.external_id or item.url or item.title
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)

        return unique
