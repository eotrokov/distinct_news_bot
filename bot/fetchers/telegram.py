from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from bot.fetchers.base import BaseFetcher, FetchError
from bot.models import NewsItem, Source
from bot.summarize import clean_and_summarize, first_meaningful_line

_HANDLE_RE = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?@?([A-Za-z0-9_]{4,})$")


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


class TelegramChannelFetcher(BaseFetcher):
    """Fetch public channel posts via the web preview https://t.me/s/<channel>."""

    source_type = "telegram"

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    async def fetch(self, source: Source) -> list[NewsItem]:
        handle = normalize_telegram_handle(source.identifier)
        url = f"https://t.me/s/{handle}"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": "distinct-news-bot/0.1"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
        except httpx.HTTPError as exc:
            raise FetchError(f"Не удалось открыть канал @{handle}") from exc

        soup = BeautifulSoup(html, "lxml")
        widgets = soup.select("div.tgme_widget_message")
        if not widgets:
            raise FetchError(
                f"Канал @{handle} недоступен как публичный (нужен открытый канал)"
            )

        items: list[NewsItem] = []
        for widget in widgets:
            post_url = ""
            link = widget.select_one("a.tgme_widget_message_date")
            if link and link.get("href"):
                post_url = link["href"]
            data_post = widget.get("data-post") or ""
            if not post_url and data_post:
                post_url = f"https://t.me/{data_post}"

            text_node = widget.select_one("div.tgme_widget_message_text")
            text = text_node.get_text("\n", strip=True) if text_node else ""
            if not text:
                # Media-only posts: use caption fallback or skip.
                continue

            title = first_meaningful_line(text, max_len=240) or text.split("\n", 1)[0][:240]
            published_at = None
            time_node = widget.select_one("time")
            if time_node and time_node.get("datetime"):
                try:
                    published_at = datetime.fromisoformat(
                        time_node["datetime"].replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                except ValueError:
                    published_at = None

            items.append(
                NewsItem(
                    title=title,
                    url=post_url,
                    published_at=published_at,
                    source_type="telegram",
                    source_name=source.title or f"@{handle}",
                    summary=clean_and_summarize(text, title=title) or None,
                    external_id=data_post or post_url or title,
                )
            )
        return items
