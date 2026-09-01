from __future__ import annotations

from dataclasses import dataclass

from bot.addlist import FolderChannel


@dataclass(frozen=True)
class PresetItem:
    identifier: str
    title: str
    source_type: str = "telegram"


@dataclass(frozen=True)
class ChannelPreset:
    slug: str
    title: str
    description: str
    addlist_url: str | None
    channels: tuple[FolderChannel | PresetItem, ...]

    @property
    def count(self) -> int:
        return len(self.channels)


CHANNEL_PRESETS: tuple[ChannelPreset, ...] = (
    ChannelPreset(
        slug="seo-igaming",
        title="SEO / iGaming (Telegram)",
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
    ChannelPreset(
        slug="seo-blogs-rss",
        title="SEO Блоги (RSS)",
        description="Ahrefs, Backlinko, Moz, SEJ, SEL, Semrush, Google, Screaming Frog и др.",
        addlist_url=None,
        channels=(
            PresetItem("https://ahrefs.com/blog/feed/", "Ahrefs Blog", "rss"),
            PresetItem("https://backlinko.com/feed", "Backlinko", "rss"),
            PresetItem("https://moz.com/posts/rss/blog", "Moz Blog", "rss"),
            PresetItem("https://www.searchenginejournal.com/feed/", "Search Engine Journal", "rss"),
            PresetItem("https://searchengineland.com/feed", "Search Engine Land", "rss"),
            PresetItem("https://www.semrush.com/blog/feed/", "Semrush Blog", "rss"),
            PresetItem("https://developers.google.com/search/blog/rss.xml", "Google Search Central Blog", "rss"),
            PresetItem("https://www.screamingfrog.co.uk/feed/", "Screaming Frog Blog", "rss"),
            PresetItem("https://www.aleydasolis.com/en/feed/", "Aleyda Solis", "rss"),
            PresetItem("https://www.mariehaynes.com/feed/", "Marie Haynes", "rss"),
        ),
    ),
)


def get_channel_preset(slug: str) -> ChannelPreset | None:
    for preset in CHANNEL_PRESETS:
        if preset.slug == slug:
            return preset
    return None
