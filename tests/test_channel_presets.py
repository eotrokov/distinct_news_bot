from __future__ import annotations

from bot.channel_presets import get_channel_preset
from bot.db import Database
from bot.sources_ops import add_telegram_channels


def test_seo_igaming_preset_channels():
    preset = get_channel_preset("seo-igaming")

    assert preset is not None
    assert preset.addlist_url == "https://t.me/addlist/_0flf9ViWOo0NjNi"
    assert [channel.username for channel in preset.channels] == [
        "SEO_for_iGaming",
        "gonzo_ML",
        "burzhunet",
        "alaevseo",
        "bez_seo",
        "seoreposts",
        "seo4robots",
        "shakinru",
        "notjohnmu",
        "seolife",
        "sealytics",
    ]


def test_add_channel_preset_respects_plan_limit(tmp_path):
    preset = get_channel_preset("seo-igaming")
    assert preset is not None
    db = Database(str(tmp_path / "presets.sqlite3"))
    uid = 101

    added, skipped = add_telegram_channels(db, uid, list(preset.channels))

    assert added == [
        "@seo_for_igaming",
        "@gonzo_ml",
        "@burzhunet",
        "@alaevseo",
        "@bez_seo",
    ]
    assert len(skipped) == len(preset.channels) - len(added)
    assert all("лимит плана 5" in item for item in skipped)
