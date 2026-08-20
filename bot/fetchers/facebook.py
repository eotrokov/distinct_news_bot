from __future__ import annotations

import re
from urllib.parse import quote

from bot.fetchers.base import BaseFetcher, FetchError
from bot.fetchers.rss import RssFetcher
from bot.models import NewsItem, Source

_FB_PAGE_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?facebook\.com/([A-Za-z0-9.]+)(?:/)?$",
    re.IGNORECASE,
)


def normalize_facebook_target(value: str) -> str:
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://"):
        if "facebook.com" in value.lower():
            match = _FB_PAGE_RE.match(value)
            if match:
                return match.group(1)
            return value  # treat as direct RSS URL if user provided one
        return value
    return value.lstrip("@")


class FacebookFetcher(BaseFetcher):
    """Facebook pages via RSSHub (or a direct RSS URL)."""

    source_type = "facebook"

    def __init__(self, rss: RssFetcher, rsshub_base_url: str | None) -> None:
        self.rss = rss
        self.rsshub_base_url = (rsshub_base_url or "").rstrip("/") or None

    async def fetch(self, source: Source) -> list[NewsItem]:
        target = normalize_facebook_target(source.identifier)
        if target.startswith("http://") or target.startswith("https://"):
            feed_url = target
        else:
            if not self.rsshub_base_url:
                raise FetchError(
                    "Для Facebook нужен RSSHUB_BASE_URL или прямой URL RSS-ленты страницы"
                )
            feed_url = f"{self.rsshub_base_url}/facebook/page/{quote(target)}"

        return await self.rss.fetch_url(
            feed_url,
            source_type="facebook",
            source_name=source.title or f"FB:{target}",
        )
