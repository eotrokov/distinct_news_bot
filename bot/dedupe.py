from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

from bot.models import NewsItem

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title or "").lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def _normalize_body(item: NewsItem) -> str:
    """Title + summary for cross-source duplicate detection."""
    parts = [item.title or "", item.summary or ""]
    return normalize_title(" ".join(parts))


def fingerprint_for(item: NewsItem) -> str:
    """Stable fingerprint used for exact/near-duplicate tracking."""
    normalized = normalize_title(item.title)
    if normalized:
        payload = f"title:{normalized}"
    elif item.url:
        payload = f"url:{item.url.strip().lower()}"
    else:
        payload = f"raw:{item.title}|{item.url}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _token_set(text: str) -> set[str]:
    return {t for t in normalize_title(text).split() if len(t) > 2}


def are_near_duplicates(a: NewsItem, b: NewsItem, threshold: float = 0.86) -> bool:
    if a.url and b.url and a.url.rstrip("/") == b.url.rstrip("/"):
        return True

    ta = normalize_title(a.title)
    tb = normalize_title(b.title)
    if ta and tb:
        if ta == tb:
            return True
        ratio = SequenceMatcher(None, ta, tb).ratio()
        if ratio >= threshold:
            return True
        sa, sb = _token_set(a.title), _token_set(b.title)
        if sa and sb:
            jaccard = len(sa & sb) / len(sa | sb)
            if jaccard >= 0.75 and ratio >= 0.72:
                return True

    # Same story rewritten across channels: compare body/summary.
    ba, bb = _normalize_body(a), _normalize_body(b)
    if len(ba) >= 40 and len(bb) >= 40:
        body_ratio = SequenceMatcher(None, ba[:500], bb[:500]).ratio()
        if body_ratio >= 0.82:
            return True
        sa, sb = _token_set(ba), _token_set(bb)
        if sa and sb:
            jaccard = len(sa & sb) / len(sa | sb)
            if jaccard >= 0.7 and body_ratio >= 0.68:
                return True

    return False


def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    """Drop duplicates across sources, keeping the earliest published item."""

    def sort_key(item: NewsItem) -> tuple:
        published = item.published_at.timestamp() if item.published_at else float("inf")
        return (published, item.title)

    ordered = sorted(items, key=sort_key)
    unique: list[NewsItem] = []
    seen_fp: set[str] = set()

    for item in ordered:
        fp = fingerprint_for(item)
        if fp in seen_fp:
            continue
        if any(are_near_duplicates(item, kept) for kept in unique):
            continue
        seen_fp.add(fp)
        unique.append(item)

    return unique
