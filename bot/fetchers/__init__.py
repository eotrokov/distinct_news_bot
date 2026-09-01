from __future__ import annotations

# Re-export fetchers for convenience.
from bot.fetchers.base import BaseFetcher, FetchError
from bot.fetchers.rss import RssFeedFetcher, default_rss_title, normalize_rss_url
from bot.fetchers.telegram import TelegramChannelFetcher, normalize_telegram_handle

__all__ = [
    "BaseFetcher",
    "FetchError",
    "RssFeedFetcher",
    "TelegramChannelFetcher",
    "default_rss_title",
    "normalize_rss_url",
    "normalize_telegram_handle",
]
