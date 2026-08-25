from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


SourceType = Literal["telegram", "rss", "ria", "facebook", "twitter"]
# Product surface is Telegram-only; legacy types may still exist in SQLite.


@dataclass(frozen=True)
class Source:
    id: int
    user_id: int
    source_type: SourceType
    identifier: str
    title: str
    created_at: datetime


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    published_at: datetime | None
    source_type: SourceType
    source_name: str
    summary: str = ""
    body: str = ""
    external_id: str = ""
    urls: list[str] = field(default_factory=list)
    reactions: int = 0
    views: int = 0
