from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bot.fetchers.rss import RssFeedFetcher, default_rss_title, normalize_rss_url
from bot.models import Source


def _source(url: str = "https://example.com/feed.xml") -> Source:
    return Source(
        id=1,
        user_id=42,
        source_type="rss",
        identifier=url,
        title="Example Feed",
        created_at=datetime.now(timezone.utc),
    )


def test_normalize_rss_url():
    assert normalize_rss_url("https://example.com/feed/") == "https://example.com/feed/"
    assert default_rss_title("https://www.example.com/feed/") == "example.com"
    with pytest.raises(ValueError):
        normalize_rss_url("@channel")


@pytest.mark.asyncio
async def test_rss_fetcher_parses_rss_items():
    xml = """\
    <rss version="2.0">
      <channel>
        <item>
          <title>Google released a search ranking update</title>
          <link>https://example.com/google-update</link>
          <guid>post-1</guid>
          <pubDate>Tue, 01 Sep 2026 10:30:00 GMT</pubDate>
          <description><![CDATA[
            <p>Google released a search ranking update for SEO specialists.</p>
            <p>Search Console reports may change over the next few days.</p>
          ]]></description>
        </item>
      </channel>
    </rss>
    """

    class FakeHttp:
        async def get_text(self, url: str) -> str:
            assert url == "https://example.com/feed.xml"
            return xml

    fetcher = RssFeedFetcher(http=FakeHttp())  # type: ignore[arg-type]
    items = await fetcher.fetch(_source())

    assert len(items) == 1
    item = items[0]
    assert item.source_type == "rss"
    assert item.source_name == "Example Feed"
    assert item.title == "Google released a search ranking update"
    assert item.url == "https://example.com/google-update"
    assert item.external_id == "post-1"
    assert item.published_at == datetime(2026, 9, 1, 10, 30, tzinfo=timezone.utc)
    assert "ranking update" in item.body


@pytest.mark.asyncio
async def test_rss_fetcher_parses_atom_and_filters_since():
    xml = """\
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Fresh SEO analytics tools for Google reports</title>
        <link href="https://example.com/fresh" rel="alternate" />
        <id>tag:example.com,2026:fresh</id>
        <updated>2026-09-01T12:00:00Z</updated>
        <summary>Analytics teams can inspect Google search traffic faster.</summary>
      </entry>
      <entry>
        <title>Old Search Console note</title>
        <link href="https://example.com/old" />
        <id>tag:example.com,2026:old</id>
        <updated>2026-08-01T12:00:00Z</updated>
        <summary>Old Google Search Console note.</summary>
      </entry>
    </feed>
    """

    class FakeHttp:
        async def get_text(self, url: str) -> str:
            return xml

    fetcher = RssFeedFetcher(http=FakeHttp())  # type: ignore[arg-type]
    items = await fetcher.fetch(
        _source(),
        since=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert [item.url for item in items] == ["https://example.com/fresh"]
