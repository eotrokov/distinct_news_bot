from __future__ import annotations

# Re-export fetchers for convenience.
from bot.fetchers.base import BaseFetcher, FetchError
from bot.fetchers.facebook import FacebookFetcher
from bot.fetchers.ria import RiaFetcher, RIA_FEEDS
from bot.fetchers.rss import RssFetcher
from bot.fetchers.telegram import TelegramChannelFetcher, normalize_telegram_handle
from bot.fetchers.twitter import TwitterFetcher

__all__ = [
    "BaseFetcher",
    "FetchError",
    "FacebookFetcher",
    "RiaFetcher",
    "RIA_FEEDS",
    "RssFetcher",
    "TelegramChannelFetcher",
    "normalize_telegram_handle",
    "TwitterFetcher",
]
