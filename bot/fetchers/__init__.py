from __future__ import annotations

# Re-export fetchers for convenience.
from bot.fetchers.base import BaseFetcher, FetchError
from bot.fetchers.rss import (
    RssFetcher,
    looks_like_rss_url,
    normalize_rss_url,
    parse_rss_urls,
    rss_title_from_url,
)
from bot.fetchers.telegram import TelegramChannelFetcher, normalize_telegram_handle

__all__ = [
    "BaseFetcher",
    "FetchError",
    "RssFetcher",
    "TelegramChannelFetcher",
    "looks_like_rss_url",
    "normalize_rss_url",
    "normalize_telegram_handle",
    "parse_rss_urls",
    "rss_title_from_url",
]
