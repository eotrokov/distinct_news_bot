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
    return {
        t
        for t in normalize_title(text).split()
        if t.isdigit() or len(t) > 2
    }


def _compare_text(item: NewsItem) -> str:
    """Title plus a short excerpt from summary/body for cross-source matching."""
    parts = [item.title or ""]
    extra = (item.summary or item.body or "").strip()
    if extra:
        parts.append(extra[:240])
    return " ".join(parts)


def are_near_duplicates(a: NewsItem, b: NewsItem, threshold: float = 0.86) -> bool:
    if a.url and b.url and a.url.rstrip("/") == b.url.rstrip("/"):
        return True

    text_a = _compare_text(a)
    text_b = _compare_text(b)
    ta = normalize_title(text_a)
    tb = normalize_title(text_b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True

    ratio = SequenceMatcher(None, ta, tb).ratio()
    if ratio >= threshold:
        return True

    sa, sb = _token_set(text_a), _token_set(text_b)
    if not sa or not sb:
        return False
    jaccard = len(sa & sb) / len(sa | sb)
    if jaccard >= 0.75 and ratio >= 0.72:
        return True

    inter = sa & sb
    if len(inter) >= 3:
        containment = len(inter) / min(len(sa), len(sb))
        if containment >= 0.5 and ratio >= 0.4:
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
