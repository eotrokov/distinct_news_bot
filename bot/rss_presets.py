from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RssFeed:
    name: str
    url: str


SEO_RSS_FEEDS: tuple[RssFeed, ...] = (
    RssFeed("Ahrefs Blog", "https://ahrefs.com/blog/feed/"),
    RssFeed("Backlinko", "https://backlinko.com/feed"),
    RssFeed("Moz Blog", "https://moz.com/posts/rss/blog"),
    RssFeed("Search Engine Journal", "https://www.searchenginejournal.com/feed/"),
    RssFeed("Search Engine Land", "https://searchengineland.com/feed"),
    RssFeed("Semrush Blog", "https://www.semrush.com/blog/feed/"),
    RssFeed(
        "Google Search Central Blog",
        "https://developers.google.com/search/blog/rss.xml",
    ),
    RssFeed("Screaming Frog Blog", "https://www.screamingfrog.co.uk/feed/"),
    RssFeed("Aleyda Solis", "https://www.aleydasolis.com/en/feed/"),
    RssFeed("Marie Haynes", "https://www.mariehaynes.com/feed/"),
)
