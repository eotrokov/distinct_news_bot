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


def get_channel_preset(slug: str) -> ChannelPreset | None:
    for preset in CHANNEL_PRESETS:
        if preset.slug == slug:
            return preset
    return None
