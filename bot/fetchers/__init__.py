from __future__ import annotations

# Re-export fetchers for convenience.
from bot.fetchers.base import BaseFetcher, FetchError
from bot.fetchers.telegram import TelegramChannelFetcher, normalize_telegram_handle

__all__ = [
    "BaseFetcher",
    "FetchError",
    "TelegramChannelFetcher",
    "normalize_telegram_handle",
]
