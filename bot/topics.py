from __future__ import annotations

import re
import shlex
import unicodedata

TopicKind = str  # "include" | "exclude"

KIND_INCLUDE = "include"
KIND_EXCLUDE = "exclude"


def normalize_topic(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    if not text:
        raise ValueError("Тема пустая")
    if len(text) > 80:
        raise ValueError("Тема слишком длинная (макс. 80 символов)")
    return text


def normalize_kind(raw: str | None) -> TopicKind:
    value = (raw or KIND_INCLUDE).strip().lower()
    if value in {
        KIND_INCLUDE,
        "in",
        "pos",
        "positive",
        "+",
        "show",
        "whitelist",
        "allow",
    }:
        return KIND_INCLUDE
    if value in {
        KIND_EXCLUDE,
        "ex",
        "neg",
        "negative",
        "-",
        "hide",
        "ban",
        "block",
        "blacklist",
        "deny",
    }:
        return KIND_EXCLUDE
    raise ValueError("Тип темы: include (показывать) или exclude (скрывать)")


def parse_topic_args(args: list[str]) -> list[str]:
    """Parse one or more topics from command args.

    Examples:
      seo
      seo marketing
      seo,marketing
      "search engine"
    """
    if not args:
        raise ValueError("Укажите тему, например: /topic add seo")

    joined = " ".join(args).strip()
    # Normalize commas to spaces, then shlex-split so quotes keep phrases.
    joined = re.sub(r"[,;]+", " ", joined)
    try:
        tokens = shlex.split(joined)
    except ValueError:
        tokens = joined.split()

    parts = [normalize_topic(t) for t in tokens if t.strip()]
    if not parts:
        raise ValueError("Укажите тему, например: /topic add seo")

    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def item_matches_topics(title: str, summary: str, topics: list[str]) -> bool:
    """True if text matches any topic. Empty topics → no match for callers that care."""
    if not topics:
        return False
    haystack = f"{title or ''}\n{summary or ''}".lower()
    haystack = unicodedata.normalize("NFKC", haystack)
    for topic in topics:
        if topic in haystack:
            return True
        pattern = re.compile(rf"(?<!\w){re.escape(topic)}(?!\w)", re.IGNORECASE)
        if pattern.search(haystack):
            return True
    return False


def item_passes_topic_filters(
    title: str,
    summary: str,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> bool:
    """Apply positive (include) and negative (exclude) topic filters.

    - exclude match → drop
    - if include list non-empty → keep only matches
    - if include empty → keep all that are not excluded
    """
    include = include or []
    exclude = exclude or []
    if exclude and item_matches_topics(title, summary, exclude):
        return False
    if include and not item_matches_topics(title, summary, include):
        return False
    return True
