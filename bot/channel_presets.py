from __future__ import annotations

from dataclasses import dataclass

from bot.addlist import FolderChannel


@dataclass(frozen=True)
class ChannelPreset:
    slug: str
    title: str
    description: str
    addlist_url: str | None
    channels: tuple[FolderChannel, ...]

    @property
    def count(self) -> int:
        return len(self.channels)


CHANNEL_PRESETS: tuple[ChannelPreset, ...] = (
    ChannelPreset(
        slug="seo-igaming",
        title="SEO / iGaming",
        description="SEO, iGaming, аналитика и практические заметки",
        addlist_url="https://t.me/addlist/_0flf9ViWOo0NjNi",
        channels=(
            FolderChannel("SEO_for_iGaming", "@SEO_for_iGaming"),
            FolderChannel("gonzo_ML", "@gonzo_ML"),
            FolderChannel("burzhunet", "@burzhunet"),
            FolderChannel("alaevseo", "@alaevseo"),
            FolderChannel("bez_seo", "@bez_seo"),
            FolderChannel("seoreposts", "@seoreposts"),
            FolderChannel("seo4robots", "@seo4robots"),
            FolderChannel("shakinru", "@shakinru"),
            FolderChannel("notjohnmu", "@notjohnmu"),
            FolderChannel("seolife", "@seolife"),
            FolderChannel("sealytics", "@sealytics"),
        ),
    ),
)


@dataclass(frozen=True)
class RssFeed:
    url: str
    title: str


@dataclass(frozen=True)
class RssPreset:
    slug: str
    title: str
    description: str
    feeds: tuple[RssFeed, ...]

    @property
    def count(self) -> int:
        return len(self.feeds)


# SEO blogs from the original rss2tg feed list.
RSS_PRESETS: tuple[RssPreset, ...] = (
    RssPreset(
        slug="seo-blogs",
        title="SEO-блоги (RSS)",
        description="Ahrefs, Moz, SEJ, Search Engine Land, Semrush, Google Search Central и другие",
        feeds=(
            RssFeed("https://ahrefs.com/blog/feed/", "Ahrefs Blog"),
            RssFeed("https://backlinko.com/feed", "Backlinko"),
            RssFeed("https://moz.com/posts/rss/blog", "Moz Blog"),
            RssFeed(
                "https://www.searchenginejournal.com/feed/",
                "Search Engine Journal",
            ),
            RssFeed("https://searchengineland.com/feed", "Search Engine Land"),
            RssFeed("https://www.semrush.com/blog/feed/", "Semrush Blog"),
            RssFeed(
                "https://developers.google.com/search/blog/rss.xml",
                "Google Search Central Blog",
            ),
            RssFeed(
                "https://www.screamingfrog.co.uk/feed/",
                "Screaming Frog Blog",
            ),
            RssFeed("https://www.aleydasolis.com/en/feed/", "Aleyda Solis"),
            RssFeed("https://www.mariehaynes.com/feed/", "Marie Haynes"),
        ),
    ),
)


def get_channel_preset(slug: str) -> ChannelPreset | None:
    for preset in CHANNEL_PRESETS:
        if preset.slug == slug:
            return preset
    return None


def get_rss_preset(slug: str) -> RssPreset | None:
    for preset in RSS_PRESETS:
        if preset.slug == slug:
            return preset
    return None
