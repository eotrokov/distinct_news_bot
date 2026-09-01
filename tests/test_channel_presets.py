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


def test_seo_blogs_rss_preset():
    preset = get_channel_preset("seo-blogs-rss")
    assert preset is not None
    assert preset.count == 10
    assert any("Ahrefs Blog" in ch.title for ch in preset.channels)
    assert any("https://backlinko.com/feed" == ch.identifier for ch in preset.channels)
    assert any("https://developers.google.com/search/blog/rss.xml" == ch.identifier for ch in preset.channels)


def test_add_channel_preset_fits_trial_plan_limit(tmp_path):
    preset = get_channel_preset("seo-igaming")
    assert preset is not None
    db = Database(str(tmp_path / "presets.sqlite3"))
    uid = 101

    from bot.sources_ops import add_preset_sources

    added, skipped = add_preset_sources(db, uid, preset.channels)

    assert added == [
        "@seo_for_igaming",
        "@gonzo_ml",
        "@burzhunet",
        "@alaevseo",
        "@bez_seo",
        "@seoreposts",
        "@seo4robots",
        "@shakinru",
        "@notjohnmu",
        "@seolife",
        "@sealytics",
    ]
    assert skipped == []


def test_add_rss_preset_sources(tmp_path):
    preset = get_channel_preset("seo-blogs-rss")
    assert preset is not None
    db = Database(str(tmp_path / "presets_rss.sqlite3"))
    uid = 102

    from bot.sources_ops import add_preset_sources

    added, skipped = add_preset_sources(db, uid, preset.channels)
    assert len(added) == 10
    assert skipped == []
    sources = db.list_sources(uid)
    assert len(sources) == 10
    assert all(s.source_type == "rss" for s in sources)
