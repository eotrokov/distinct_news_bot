from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


SourceType = Literal["telegram", "rss", "ria", "facebook", "twitter"]


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
    external_id: str = ""
