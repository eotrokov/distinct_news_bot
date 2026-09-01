from __future__ import annotations

from bot.channel_presets import get_channel_preset, get_rss_preset
from bot.db import Database
from bot.sources_ops import add_rss_feeds, add_telegram_channels


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


def test_add_channel_preset_fits_trial_plan_limit(tmp_path):
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
        "@seoreposts",
        "@seo4robots",
        "@shakinru",
        "@notjohnmu",
        "@seolife",
        "@sealytics",
    ]
    assert skipped == []


def test_seo_blogs_rss_preset():
    preset = get_rss_preset("seo-blogs")
    assert preset is not None
    assert preset.count == 11
    assert [feed.title for feed in preset.feeds] == [
        "Ahrefs Blog",
        "Backlinko",
        "Moz Blog",
        "Search Engine Journal",
        "Search Engine Land",
        "Semrush Blog",
        "Google Search Central Blog",
        "Google Search Central Docs",
        "Screaming Frog Blog",
        "Aleyda Solis",
        "Marie Haynes",
    ]


def test_add_rss_preset_fits_trial_plan_limit(tmp_path):
    preset = get_rss_preset("seo-blogs")
    assert preset is not None
    db = Database(str(tmp_path / "rss-presets.sqlite3"))
    uid = 202

    added, skipped = add_rss_feeds(db, uid, list(preset.feeds))

    assert skipped == []
    assert len(added) == 11
    assert added[0] == "Ahrefs Blog"
    sources = db.list_sources(uid)
    assert all(s.source_type == "rss" for s in sources)
    assert {s.identifier for s in sources} == {
        "https://ahrefs.com/blog/feed",
        "https://backlinko.com/feed",
        "https://moz.com/posts/rss/blog",
        "https://www.searchenginejournal.com/feed",
        "https://searchengineland.com/feed",
        "https://www.semrush.com/blog/feed",
        "https://feeds.feedburner.com/blogspot/amDG",
        "https://developers.google.com/search/updates/search_docs_updates.rss",
        "https://www.screamingfrog.co.uk/feed",
        "https://www.aleydasolis.com/en/feed",
        "https://www.mariehaynes.com/feed",
    }
