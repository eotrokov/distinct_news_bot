from __future__ import annotations

from datetime import datetime, timezone

from bot.channel_presets import RSS_PRESETS
from bot.fetchers.rss import normalize_rss_url
from bot.models import Source

# Negative ids so /remove cannot hit a real user row.
_BUILTIN_ID_BASE = -1000


def builtin_rss_sources() -> list[Source]:
    """SEO blog feeds included in every digest; they do not use plan slots."""
    now = datetime.now(timezone.utc)
    items: list[Source] = []
    index = 0
    for preset in RSS_PRESETS:
        for feed in preset.feeds:
            index += 1
            items.append(
                Source(
                    id=_BUILTIN_ID_BASE - index,
                    user_id=0,
                    source_type="rss",
                    identifier=normalize_rss_url(feed.url),
                    title=feed.title,
                    created_at=now,
                )
            )
    return items


def merge_sources(user_sources: list[Source]) -> list[Source]:
    """Builtin RSS first, then the user's own sources. Skip URL duplicates."""
    seen = {(s.source_type, s.identifier) for s in user_sources}
    extra = [
        source
        for source in builtin_rss_sources()
        if (source.source_type, source.identifier) not in seen
    ]
    return extra + list(user_sources)
