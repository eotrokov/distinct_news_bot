from __future__ import annotations

# Re-export fetchers for convenience.
from bot.fetchers.base import BaseFetcher, FetchError
from bot.fetchers.rss import RSSFetcher, normalize_rss_url
from bot.fetchers.telegram import TelegramChannelFetcher, normalize_telegram_handle

__all__ = [
    "BaseFetcher",
    "FetchError",
    "RSSFetcher",
    "TelegramChannelFetcher",
    "normalize_rss_url",
    "normalize_telegram_handle",
]
