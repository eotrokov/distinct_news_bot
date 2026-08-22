from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup, Tag

from bot.fetchers.base import BaseFetcher, FetchError
from bot.models import NewsItem, Source
from bot.summarize import clean_and_summarize, clean_text, first_meaningful_line

_HANDLE_RE = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?@?([A-Za-z0-9_]{4,})$")
_COUNT_RE = re.compile(r"([\d.,]+)\s*([KkMmBb])?")


def normalize_telegram_handle(value: str) -> str:
    value = value.strip()
    match = _HANDLE_RE.match(value)
    if match:
        return match.group(1)
    if re.fullmatch(r"@?[A-Za-z0-9_]{4,}", value):
        return value.lstrip("@")
    raise ValueError(
        "Укажите публичный Telegram-канал: @channel, channel или https://t.me/channel"
    )


def parse_count(raw: str | None) -> int:
    """Parse Telegram abbreviated counts like 12.5M, 7.03K, 824."""
    if not raw:
        return 0
    text = raw.replace("\u202f", "").replace(" ", "").strip()
    match = _COUNT_RE.fullmatch(text)
    if not match:
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else 0
    number = float(match.group(1).replace(",", "."))
    suffix = (match.group(2) or "").upper()
    mult = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(number * mult)


def _extract_reactions(widget: Tag) -> int:
    total = 0
    for node in widget.select("span.tgme_reaction"):
        total += parse_count(node.get_text(" ", strip=True))
    return total


def _extract_views(widget: Tag) -> int:
    node = widget.select_one("span.tgme_widget_message_views")
    return parse_count(node.get_text(" ", strip=True) if node else "")


class TelegramChannelFetcher(BaseFetcher):
    """Fetch public channel posts via the web preview https://t.me/s/<channel>."""

    source_type = "telegram"

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    async def fetch(
        self,
        source: Source,
        *,
        since: datetime | None = None,
        max_pages: int = 1,
    ) -> list[NewsItem]:
        handle = normalize_telegram_handle(source.identifier)
        items: list[NewsItem] = []
        before: int | None = None
        pages = max(1, int(max_pages))

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": "distinct-news-bot/0.1"},
        ) as client:
            for _ in range(pages):
                url = f"https://t.me/s/{handle}"
                if before is not None:
                    url = f"{url}?before={before}"
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    html = response.text
                except httpx.HTTPError as exc:
                    if items:
                        break
                    raise FetchError(f"Не удалось открыть канал @{handle}") from exc

                page_items, oldest_id = self._parse_page(html, source, handle)
                if not page_items and not items:
                    raise FetchError(
                        f"Канал @{handle} недоступен как публичный (нужен открытый канал)"
                    )
                if not page_items:
                    break

                stop = False
                for item in page_items:
                    if since and item.published_at and item.published_at < since:
                        stop = True
                        continue
                    items.append(item)
                if stop or oldest_id is None:
                    break
                before = oldest_id

        # Newest first, unique by external_id/url.
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

    def _parse_page(
        self, html: str, source: Source, handle: str
    ) -> tuple[list[NewsItem], int | None]:
        soup = BeautifulSoup(html, "lxml")
        widgets = soup.select("div.tgme_widget_message")
        items: list[NewsItem] = []
        oldest_id: int | None = None

        for widget in widgets:
            data_post = widget.get("data-post") or ""
            post_url = ""
            link = widget.select_one("a.tgme_widget_message_date")
            if link and link.get("href"):
                post_url = str(link["href"])
            if not post_url and data_post:
                post_url = f"https://t.me/{data_post}"

            text_node = widget.select_one("div.tgme_widget_message_text")
            text = text_node.get_text("\n", strip=True) if text_node else ""
            if not text:
                continue

            title = first_meaningful_line(text, max_len=240) or text.split("\n", 1)[0][:240]
            published_at = None
            time_node = widget.select_one("time")
            if time_node and time_node.get("datetime"):
                try:
                    published_at = datetime.fromisoformat(
                        str(time_node["datetime"]).replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                except ValueError:
                    published_at = None

            msg_id = None
            if "/" in data_post:
                raw_id = data_post.rsplit("/", 1)[-1]
                if raw_id.isdigit():
                    msg_id = int(raw_id)
                    oldest_id = msg_id if oldest_id is None else min(oldest_id, msg_id)

            body = clean_text(text)[:2000] or None
            items.append(
                NewsItem(
                    title=title,
                    url=post_url,
                    published_at=published_at,
                    source_type="telegram",
                    source_name=source.title or f"@{handle}",
                    summary=clean_and_summarize(
                        text, title=title, max_sentences=5, max_len=900
                    )
                    or None,
                    body=body,
                    external_id=data_post or post_url or title,
                    reactions=_extract_reactions(widget),
                    views=_extract_views(widget),
                )
            )
        return items, oldest_id
