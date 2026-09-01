from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bot.db import Database
from bot.digest import parse_add_args
from bot.fetchers.rss import RSSFetcher, normalize_rss_url
from bot.models import Source
from bot.sources_ops import add_single_source


RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>SEO News</title>
    <item>
      <guid>article-1</guid>
      <title>Google confirms a new ranking update</title>
      <link>https://example.com/article-1</link>
      <pubDate>Mon, 01 Sep 2026 10:30:00 GMT</pubDate>
      <description>Google published details about a ranking update.</description>
    </item>
  </channel>
</rss>"""


def test_parse_rss_add_arguments():
    source_type, identifier, title = parse_add_args(
        ["rss", "https://example.com/feed.xml", "Example", "Feed"]
    )
    assert source_type == "rss"
    assert identifier == "https://example.com/feed.xml"
    assert title == "Example Feed"


def test_add_rss_source(tmp_path):
    db = Database(str(tmp_path / "bot.sqlite3"))
    source = add_single_source(
        db, 42, "rss", "https://example.com/feed.xml", "Example Feed"
    )
    assert source.source_type == "rss"
    assert source.identifier == "https://example.com/feed.xml"


@pytest.mark.parametrize(
    "url",
    [
        "example.com/feed",
        "ftp://example.com/feed",
        "",
        "http://localhost/feed",
        "http://127.0.0.1/feed",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_normalize_rss_url_rejects_non_http_urls(url: str):
    with pytest.raises(ValueError):
        normalize_rss_url(url)


@pytest.mark.asyncio
async def test_rss_fetcher_parses_items_and_honors_since():
    class FakeHttp:
        async def get_text(self, url: str, *, follow_redirects: bool = True) -> str:
            assert url == "https://example.com/feed.xml"
            assert not follow_redirects
            return RSS_XML

    source = Source(
        id=1,
        user_id=42,
        source_type="rss",
        identifier="https://example.com/feed.xml",
        title="Example Feed",
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    fetcher = RSSFetcher(http=FakeHttp())  # type: ignore[arg-type]
    items = await fetcher.fetch(
        source, since=datetime(2026, 9, 1, tzinfo=timezone.utc)
    )
    assert len(items) == 1
    assert items[0].external_id == "article-1"
    assert items[0].published_at == datetime(2026, 9, 1, 10, 30, tzinfo=timezone.utc)
    assert items[0].source_type == "rss"
    assert items[0].url == "https://example.com/article-1"
