from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from bot.fetchers.base import BaseFetcher, FetchError
from bot.http_util import HttpService
from bot.models import NewsItem, Source
from bot.summarize import clean_and_summarize, clean_text, first_meaningful_line


_SPACE_RE = re.compile(r"\s+")


def normalize_rss_url(value: str) -> str:
    text = value.strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Укажите RSS URL вида https://site.com/feed/")
    return text


def default_rss_title(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.")
    return host or "RSS"


def _node_text(node: Tag | None) -> str:
    if node is None:
        return ""
    text = node.get_text(" ", strip=True)
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "lxml").get_text(" ", strip=True)
    return _SPACE_RE.sub(" ", text).strip()


def _first_text(node: Tag, names: tuple[str, ...]) -> str:
    wanted = {name.lower() for name in names}
    for child in node.find_all(True, recursive=False):
        name = (child.name or "").lower()
        if name in wanted or name.split(":")[-1] in wanted:
            return _node_text(child)
    return ""


def _entry_link(node: Tag) -> str:
    direct_links = [
        child
        for child in node.find_all(True, recursive=False)
        if (child.name or "").lower().split(":")[-1] == "link"
    ]
    for link in direct_links:
        rel = str(link.get("rel") or "").lower()
        href = str(link.get("href") or "").strip()
        if href and (not rel or "alternate" in rel):
            return href
    for link in direct_links:
        href = str(link.get("href") or "").strip()
        if href:
            return href
        text = _node_text(link)
        if text:
            return text
    return ""


def _parse_datetime(raw: str) -> datetime | None:
    text = raw.strip()
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class RssFeedFetcher(BaseFetcher):
    """Fetch RSS 2.0 and Atom feeds as regular news items."""

    source_type = "rss"

    def __init__(
        self,
        timeout: float = 20.0,
        http: "HttpService | None" = None,
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
        del max_pages
        url = normalize_rss_url(source.identifier)
        own_http = self.http is None
        http = self.http or HttpService(timeout=self.timeout)
        try:
            try:
                xml = await http.get_text(url)
            except httpx.HTTPError as exc:
                raise FetchError("Не удалось открыть RSS-ленту") from exc
            items = self._parse_feed(xml, source, url)
        finally:
            if own_http:
                await http.aclose()

        if since:
            items = [
                item
                for item in items
                if item.published_at is None or item.published_at >= since
            ]

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

    def _parse_feed(self, xml: str, source: Source, feed_url: str) -> list[NewsItem]:
        soup = BeautifulSoup(xml, "xml")
        entries = soup.find_all("item")
        if not entries:
            entries = soup.find_all("entry")
        if not entries:
            raise FetchError("RSS-лента не содержит записей")

        source_name = source.title or default_rss_title(feed_url)
        items: list[NewsItem] = []
        for entry in entries:
            if not isinstance(entry, Tag):
                continue
            title = _first_text(entry, ("title",))
            link = _entry_link(entry)
            external_id = _first_text(entry, ("guid", "id")) or link or title
            raw_date = _first_text(
                entry,
                ("pubDate", "published", "updated", "date"),
            )
            published_at = _parse_datetime(raw_date)
            body = _first_text(
                entry,
                ("description", "summary", "content", "encoded"),
            )
            if not title:
                title = first_meaningful_line(body, max_len=240) or "Без заголовка"
            if not link:
                link = feed_url
            clean_body = clean_text(body or title)[:2000]
            items.append(
                NewsItem(
                    title=title[:240],
                    url=link,
                    published_at=published_at,
                    source_type="rss",
                    source_name=source_name,
                    summary=clean_and_summarize(
                        body or title,
                        title=title,
                        max_sentences=5,
                        max_len=900,
                    ),
                    body=clean_body,
                    external_id=external_id,
                )
            )
        return items
