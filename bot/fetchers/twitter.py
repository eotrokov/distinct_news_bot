from __future__ import annotations

import re
from urllib.parse import quote

from bot.fetchers.base import BaseFetcher, FetchError
from bot.fetchers.rss import RssFetcher
from bot.models import NewsItem, Source

_TW_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/@?([A-Za-z0-9_]{1,15})/?$",
    re.IGNORECASE,
)


def normalize_twitter_handle(value: str) -> str:
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://"):
        match = _TW_RE.match(value)
        if match:
            return match.group(1)
        return value  # direct RSS URL
    return value.lstrip("@")


class TwitterFetcher(BaseFetcher):
    """X/Twitter via RSSHub (or a direct RSS URL)."""

    source_type = "twitter"

    def __init__(self, rss: RssFetcher, rsshub_base_url: str | None) -> None:
        self.rss = rss
        self.rsshub_base_url = (rsshub_base_url or "").rstrip("/") or None

    async def fetch(self, source: Source) -> list[NewsItem]:
        target = normalize_twitter_handle(source.identifier)
        if target.startswith("http://") or target.startswith("https://"):
            feed_url = target
        else:
            if not self.rsshub_base_url:
                raise FetchError(
                    "Для Twitter/X нужен RSSHUB_BASE_URL или прямой URL RSS-ленты"
                )
            feed_url = f"{self.rsshub_base_url}/twitter/user/{quote(target)}"

        return await self.rss.fetch_url(
            feed_url,
            source_type="twitter",
            source_name=source.title or f"@{target}",
        )
