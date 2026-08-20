from __future__ import annotations

from bot.models import NewsItem, Source


class FetchError(RuntimeError):
    pass


class BaseFetcher:
    source_type: str

    async def fetch(self, source: Source) -> list[NewsItem]:
        raise NotImplementedError
