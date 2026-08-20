from __future__ import annotations

from bot.fetchers.base import BaseFetcher
from bot.fetchers.rss import RssFetcher
from bot.models import NewsItem, Source

# Official RIA Novosti RSS endpoints.
RIA_FEEDS: dict[str, str] = {
    "main": "https://ria.ru/export/rss2/index.xml",
    "politics": "https://ria.ru/export/rss2/politics/index.xml",
    "world": "https://ria.ru/export/rss2/world/index.xml",
    "economy": "https://ria.ru/export/rss2/economy/index.xml",
    "society": "https://ria.ru/export/rss2/society/index.xml",
    "incidents": "https://ria.ru/export/rss2/incidents/index.xml",
    "science": "https://ria.ru/export/rss2/science/index.xml",
    "culture": "https://ria.ru/export/rss2/culture/index.xml",
    "sports": "https://ria.ru/export/rss2/sports/index.xml",
}


class RiaFetcher(BaseFetcher):
    source_type = "ria"

    def __init__(self, rss: RssFetcher) -> None:
        self.rss = rss

    async def fetch(self, source: Source) -> list[NewsItem]:
        key = source.identifier.strip().lower()
        if key.startswith("http://") or key.startswith("https://"):
            feed_url = key
            name = source.title or "РИА Новости"
        else:
            feed_url = RIA_FEEDS.get(key)
            if not feed_url:
                known = ", ".join(sorted(RIA_FEEDS))
                raise ValueError(
                    f"Неизвестная лента РИА: {source.identifier}. "
                    f"Доступно: {known} или полный URL RSS"
                )
            name = source.title or f"РИА ({key})"
        return await self.rss.fetch_url(
            feed_url, source_type="ria", source_name=name
        )
