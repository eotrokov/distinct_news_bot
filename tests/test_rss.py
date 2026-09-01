from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from bot.db import Database
from bot.digest import DigestService
from bot.fetchers import RssFeedFetcher
from bot.http_util import HttpService
from bot.models import Source
from bot.config import Settings


SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Ahrefs Blog</title>
    <link>https://ahrefs.com/blog/</link>
    <description>SEO and marketing blog</description>
    <item>
      <title>Google Core Update: What You Need to Know</title>
      <link>https://ahrefs.com/blog/google-core-update/</link>
      <guid>https://ahrefs.com/blog/google-core-update/</guid>
      <pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate>
      <description><![CDATA[Google has announced a major core update to its search ranking algorithms. Here are the key findings and impact on organic traffic.]]></description>
    </item>
    <item>
      <title>10 Best Free Link Building Tools</title>
      <link>https://ahrefs.com/blog/link-building-tools/</link>
      <guid>https://ahrefs.com/blog/link-building-tools/</guid>
      <pubDate>Sun, 31 Aug 2026 09:00:00 GMT</pubDate>
      <description><![CDATA[Discover the top link building and backlink analysis tools for digital marketing professionals.]]></description>
    </item>
  </channel>
</rss>
"""


SAMPLE_ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Google Search Central Blog</title>
  <link href="https://developers.google.com/search/blog" rel="alternate"/>
  <updated>2026-09-01T10:00:00Z</updated>
  <entry>
    <title>Simplifying Search Console Crawl Reports</title>
    <link href="https://developers.google.com/search/blog/2026/09/crawl-reports"/>
    <id>tag:google.com,2026:search-console-crawl</id>
    <updated>2026-09-01T10:00:00Z</updated>
    <summary>Today we are updating the crawl stats report in Google Search Console to provide clearer insights.</summary>
  </entry>
</feed>
"""


@pytest.mark.asyncio
async def test_rss_feed_fetcher_parses_rss(monkeypatch):
    service = HttpService()

    async def fake_get(url: str, *args, **kwargs):
        return SAMPLE_RSS_XML

    monkeypatch.setattr(service, "get_text", fake_get)

    fetcher = RssFeedFetcher(http=service)
    source = Source(
        id=1,
        user_id=10,
        source_type="rss",
        identifier="https://ahrefs.com/blog/feed/",
        title="Ahrefs Blog",
        created_at=datetime.now(timezone.utc),
    )

    items = await fetcher.fetch(source)
    assert len(items) == 2
    assert items[0].title == "Google Core Update: What You Need to Know"
    assert items[0].url == "https://ahrefs.com/blog/google-core-update/"
    assert items[0].source_type == "rss"
    assert items[0].source_name == "Ahrefs Blog"
    assert items[0].published_at is not None
    assert "Google" in items[0].summary or "core update" in items[0].summary


@pytest.mark.asyncio
async def test_rss_feed_fetcher_parses_atom(monkeypatch):
    service = HttpService()

    async def fake_get(url: str, *args, **kwargs):
        return SAMPLE_ATOM_XML

    monkeypatch.setattr(service, "get_text", fake_get)

    fetcher = RssFeedFetcher(http=service)
    source = Source(
        id=2,
        user_id=10,
        source_type="rss",
        identifier="https://developers.google.com/search/blog/rss.xml",
        title="Google Search Central",
        created_at=datetime.now(timezone.utc),
    )

    items = await fetcher.fetch(source)
    assert len(items) == 1
    assert "Simplifying Search Console Crawl Reports" in items[0].title
    assert items[0].url == "https://developers.google.com/search/blog/2026/09/crawl-reports"


@pytest.mark.asyncio
async def test_digest_service_integrates_rss(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "rss_digest.sqlite3"))
    user_id = 100
    db.ensure_user(user_id)
    source = db.add_source(user_id, "rss", "https://ahrefs.com/blog/feed/", "Ahrefs Blog")

    settings = Settings(
        telegram_bot_token="fake:token",
        db_path=str(tmp_path / "rss_digest.sqlite3"),
        log_level="INFO",
        digest_limit=30,
        digest_page_size=10,
        fetch_timeout_seconds=5.0,
        fetch_concurrency=2,
        fetch_cache_ttl_seconds=60.0,
        default_lookback_hours=24,
        default_digest_days=30,
        summary_max_sentences=2,
        admin_user_ids=frozenset(),
        pro_stars_price=350,
        plus_stars_price=700,
        ai_summary_enabled=False,
        ai_provider="gemini",
        ai_api_key=None,
        ai_model="gemini-2.0-flash",
        ai_max_concurrent=4,
        ai_timeout_seconds=15.0,
    )

    digest = DigestService(db, settings)

    async def fake_get(url: str, *args, **kwargs):
        return SAMPLE_RSS_XML

    monkeypatch.setattr(digest.http, "get_text", fake_get)

    items, errors, topics, days_used, analysis = await digest.collect_for_user(user_id, days=30)
    assert len(errors) == 0
    assert len(items) >= 1
    assert any("Google" in it.title or "Link Building" in it.title for it in items)

    pages = digest.format_digest(analysis, days_used)
    assert len(pages) >= 1
    assert "SEO-дайджест" in pages[0]
    await digest.aclose()
