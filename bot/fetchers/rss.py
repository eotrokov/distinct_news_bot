from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urlunparse
from xml.etree import ElementTree as ET

import httpx

from bot.fetchers.base import BaseFetcher, FetchError
from bot.http_util import HttpService
from bot.models import NewsItem, Source
from bot.summarize import clean_and_summarize, clean_text, first_meaningful_line

_TELEGRAM_HOSTS = {"t.me", "telegram.me", "www.t.me", "www.telegram.me", "telegram.dog"}

_ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)


def looks_like_rss_url(value: str) -> bool:
    """True if the token looks like a web feed URL (not a Telegram handle)."""
    raw = (value or "").strip().strip("<>\"'")
    if not raw or raw.startswith("@"):
        return False
    lower = raw.lower()
    if any(
        host in lower
        for host in ("t.me/", "telegram.me/", "telegram.dog/")
    ):
        return False
    if lower.startswith(("http://", "https://", "www.")):
        return True
    host = raw.split("/")[0].split("?")[0]
    return "." in host and " " not in host


def normalize_rss_url(value: str) -> str:
    raw = (value or "").strip().strip("<>\"'")
    if not raw:
        raise ValueError(
            "Укажите RSS/Atom-фид: https://ahrefs.com/blog/feed/"
        )
    if not looks_like_rss_url(raw):
        raise ValueError(
            "Укажите RSS/Atom-фид: https://site.com/feed/ "
            "(не Telegram-канал)"
        )
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw.removeprefix("www.")
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError(
            "Укажите RSS/Atom-фид: https://ahrefs.com/blog/feed/"
        )
    if host in _TELEGRAM_HOSTS:
        raise ValueError(
            "Это ссылка Telegram. Добавьте канал так: /add @channel"
        )
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    return urlunparse(
        (parsed.scheme.lower(), netloc, path, "", parsed.query, "")
    )


def rss_title_from_url(url: str) -> str:
    try:
        parsed = urlparse(normalize_rss_url(url))
    except ValueError:
        parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return host or url.strip()


def parse_rss_urls(text: str) -> list[str]:
    """Extract unique RSS URLs from free-form text."""
    found: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\s,;]+", (text or "").strip()):
        token = raw.strip().strip("<>\"'")
        if not token or not looks_like_rss_url(token):
            continue
        try:
            url = normalize_rss_url(token)
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        found.append(url)
    return found


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _child_text(node: ET.Element, names: tuple[str, ...]) -> str:
    wanted = {name.lower() for name in names}
    for child in list(node):
        if _local_tag(child.tag).lower() in wanted:
            text = "".join(child.itertext()).strip()
            if text:
                return text
            href = (child.get("href") or child.get("url") or "").strip()
            if href:
                return href
    return ""


def _child_attr(node: ET.Element, names: tuple[str, ...], attr: str) -> str:
    wanted = {name.lower() for name in names}
    for child in list(node):
        if _local_tag(child.tag).lower() in wanted:
            value = (child.get(attr) or "").strip()
            if value:
                return value
    return ""


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        if _ISO_DATE_RE.match(text) or "T" in text:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _entry_link(entry: ET.Element) -> str:
    link = _child_text(entry, ("link",))
    if link.startswith("http"):
        return link
    href = _child_attr(entry, ("link",), "href")
    if href:
        return href
    return link


def _entry_body(entry: ET.Element) -> str:
    for names in (
        ("encoded", "content"),
        ("content",),
        ("summary",),
        ("description",),
    ):
        text = _child_text(entry, names)
        if text:
            return text
    return ""


def parse_feed_xml(xml: str, source: Source) -> list[NewsItem]:
    """Parse RSS 2.0 / RDF / Atom XML into NewsItem list."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise FetchError("Не удалось разобрать RSS: повреждённый XML") from exc

    channel = None
    entries: list[ET.Element] = []
    root_tag = _local_tag(root.tag).lower()
    if root_tag == "rss":
        for child in list(root):
            if _local_tag(child.tag).lower() == "channel":
                channel = child
                break
        parent = channel if channel is not None else root
        entries = [
            child for child in list(parent) if _local_tag(child.tag).lower() == "item"
        ]
    elif root_tag in {"feed", "rdf"}:
        entries = [
            child
            for child in list(root)
            if _local_tag(child.tag).lower() in {"entry", "item"}
        ]
        channel = root
    else:
        # Some feeds wrap unexpectedly; collect any item/entry.
        entries = [
            node
            for node in root.iter()
            if _local_tag(node.tag).lower() in {"item", "entry"}
        ]
        channel = root

    feed_title = ""
    if channel is not None:
        feed_title = _child_text(channel, ("title",))
    source_name = source.title or clean_text(feed_title) or rss_title_from_url(
        source.identifier
    )

    items: list[NewsItem] = []
    seen: set[str] = set()
    for entry in entries:
        title = clean_text(_child_text(entry, ("title",)))
        url = _entry_link(entry)
        raw_body = _entry_body(entry)
        body = clean_text(raw_body)[:2000]
        if not title:
            title = first_meaningful_line(body, max_len=240) or "Без заголовка"
        published = _parse_datetime(
            _child_text(entry, ("published", "updated", "pubDate", "date"))
        )
        guid = _child_text(entry, ("id", "guid")) or url or title
        key = guid or url or title
        if key in seen:
            continue
        seen.add(key)
        items.append(
            NewsItem(
                title=title[:240],
                url=url,
                published_at=published,
                source_type="rss",
                source_name=source_name,
                summary=clean_and_summarize(
                    body or title, title=title, max_sentences=5, max_len=900
                ),
                body=body,
                external_id=str(guid),
            )
        )
    return items


class RssFetcher(BaseFetcher):
    """Fetch RSS/Atom feeds over HTTP and turn entries into NewsItem."""

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
        del max_pages  # RSS is a single document.
        url = normalize_rss_url(source.identifier)
        own_http = self.http is None
        http = self.http or HttpService(timeout=self.timeout)
        try:
            try:
                xml = await http.get_text(url)
            except httpx.HTTPError as exc:
                raise FetchError(f"Не удалось открыть RSS {url}") from exc
        finally:
            if own_http:
                await http.aclose()

        items = parse_feed_xml(xml, source)
        if not items:
            raise FetchError(
                f"В фиде нет записей или это не RSS/Atom: {url}"
            )
        if since is None:
            return items
        filtered: list[NewsItem] = []
        for item in items:
            if item.published_at is not None and item.published_at < since:
                continue
            filtered.append(item)
        return filtered
