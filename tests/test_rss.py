from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bot.db import Database
from bot.fetchers.base import FetchError
from bot.fetchers.rss import (
    RssFetcher,
    looks_like_rss_url,
    normalize_rss_url,
    parse_feed_xml,
    parse_rss_urls,
    rss_title_from_url,
)
from bot.models import Source
from bot.sources_ops import add_from_text, add_rss_feeds, add_single_source


RSS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Ahrefs Blog</title>
    <item>
      <title>Google core update rolled out</title>
      <link>https://ahrefs.com/blog/core-update/</link>
      <guid>https://ahrefs.com/blog/core-update/</guid>
      <pubDate>Mon, 01 Sep 2025 10:00:00 GMT</pubDate>
      <description>Google confirmed a core update. Webmasters should monitor rankings.</description>
    </item>
    <item>
      <title>Old post about keywords</title>
      <link>https://ahrefs.com/blog/old/</link>
      <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
      <description>Keyword research basics for SEO teams and agencies worldwide.</description>
    </item>
  </channel>
</rss>
"""

ATOM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Moz Blog</title>
  <entry>
    <title>Link building in 2026</title>
    <id>urn:moz:1</id>
    <link href="https://moz.com/blog/link-building"/>
    <updated>2025-09-01T12:00:00Z</updated>
    <summary>New tactics for backlinks and E-E-A-T.</summary>
  </entry>
</feed>
"""


def _source(identifier: str = "https://ahrefs.com/blog/feed", title: str = "Ahrefs") -> Source:
    return Source(
        id=1,
        user_id=1,
        source_type="rss",
        identifier=identifier,
        title=title,
        created_at=datetime.now(timezone.utc),
    )


def test_looks_like_rss_url():
    assert looks_like_rss_url("https://ahrefs.com/blog/feed/")
    assert looks_like_rss_url("ahrefs.com/blog/feed/")
    assert not looks_like_rss_url("@bbcnews")
    assert not looks_like_rss_url("https://t.me/bbcnews")
    assert not looks_like_rss_url("meduzalive")


def test_normalize_rss_url():
    assert (
        normalize_rss_url("https://ahrefs.com/blog/feed/")
        == "https://ahrefs.com/blog/feed"
    )
    assert (
        normalize_rss_url("AHREFS.COM/blog/feed/")
        == "https://ahrefs.com/blog/feed"
    )
    with pytest.raises(ValueError):
        normalize_rss_url("https://t.me/bbcnews")
    with pytest.raises(ValueError):
        normalize_rss_url("@channel")


def test_parse_rss_urls_dedupes():
    text = (
        "https://ahrefs.com/blog/feed/ https://ahrefs.com/blog/feed "
        "https://moz.com/posts/rss/blog"
    )
    assert parse_rss_urls(text) == [
        "https://ahrefs.com/blog/feed",
        "https://moz.com/posts/rss/blog",
    ]


def test_rss_title_from_url():
    assert rss_title_from_url("https://www.ahrefs.com/blog/feed/") == "ahrefs.com"


def test_parse_rss_xml():
    items = parse_feed_xml(RSS_XML, _source())
    assert len(items) == 2
    assert items[0].title == "Google core update rolled out"
    assert items[0].url == "https://ahrefs.com/blog/core-update/"
    assert items[0].source_type == "rss"
    assert items[0].published_at is not None
    assert items[0].published_at.tzinfo is not None


def test_parse_atom_xml():
    items = parse_feed_xml(ATOM_XML, _source("https://moz.com/posts/rss/blog", "Moz"))
    assert len(items) == 1
    assert items[0].title == "Link building in 2026"
    assert items[0].url == "https://moz.com/blog/link-building"
    assert items[0].external_id == "urn:moz:1"


def test_parse_feed_xml_rejects_garbage():
    with pytest.raises(FetchError):
        parse_feed_xml("not xml at all <", _source())


@pytest.mark.asyncio
async def test_rss_fetcher_filters_since(monkeypatch: pytest.MonkeyPatch):
    fetcher = RssFetcher(timeout=5)

    async def fake_get_text(url: str, *, use_cache: bool = True) -> str:
        assert "ahrefs.com" in url
        return RSS_XML

    class DummyHttp:
        get_text = staticmethod(fake_get_text)

        async def aclose(self) -> None:
            return None

    fetcher.http = DummyHttp()  # type: ignore[assignment]
    since = datetime(2025, 6, 1, tzinfo=timezone.utc)
    items = await fetcher.fetch(_source(), since=since)
    assert [item.url for item in items] == ["https://ahrefs.com/blog/core-update/"]


@pytest.mark.asyncio
async def test_rss_fetcher_empty_raises():
    fetcher = RssFetcher(timeout=5)

    async def fake_get_text(url: str, *, use_cache: bool = True) -> str:
        return "<rss><channel><title>Empty</title></channel></rss>"

    class DummyHttp:
        get_text = staticmethod(fake_get_text)

        async def aclose(self) -> None:
            return None

    fetcher.http = DummyHttp()  # type: ignore[assignment]
    with pytest.raises(FetchError):
        await fetcher.fetch(_source())


def test_add_rss_feeds_and_from_text(tmp_path):
    db = Database(str(tmp_path / "rss.sqlite3"))
    uid = 7
    added, skipped = add_rss_feeds(
        db,
        uid,
        [
            "https://ahrefs.com/blog/feed/",
            ("https://moz.com/posts/rss/blog", "Moz Blog"),
        ],
    )
    assert added == ["ahrefs.com", "Moz Blog"]
    assert skipped == []
    added2, skipped2 = add_from_text(
        db, uid, "@bbcnews https://ahrefs.com/blog/feed/"
    )
    assert added2 == ["@bbcnews"]
    assert skipped2 == ["ahrefs.com"]
    sources = db.list_sources(uid)
    types = {s.source_type for s in sources}
    assert types == {"rss", "telegram"}


def test_add_single_rss_source(tmp_path):
    db = Database(str(tmp_path / "one.sqlite3"))
    source = add_single_source(
        db, 1, "rss", "https://ahrefs.com/blog/feed/", "Ahrefs Blog"
    )
    assert source.source_type == "rss"
    assert source.identifier == "https://ahrefs.com/blog/feed"
    assert source.title == "Ahrefs Blog"
