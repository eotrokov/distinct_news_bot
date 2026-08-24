from __future__ import annotations

import re
import shlex
import unicodedata


def normalize_topic(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    if not text:
        raise ValueError("Тема пустая")
    if len(text) > 80:
        raise ValueError("Тема слишком длинная (макс. 80 символов)")
    return text


def parse_topic_args(args: list[str]) -> list[str]:
    """Parse one or more topics from command args.

    Examples:
      ai
      ai marketing
      ai,marketing
      "search engine"
    """
    if not args:
        raise ValueError("Укажите тему, например: /topic add ai")

    joined = " ".join(args).strip()
    # Normalize commas to spaces, then shlex-split so quotes keep phrases.
    joined = re.sub(r"[,;]+", " ", joined)
    try:
        tokens = shlex.split(joined)
    except ValueError:
        tokens = joined.split()

    parts = [normalize_topic(t) for t in tokens if t.strip()]
    if not parts:
        raise ValueError("Укажите тему, например: /topic add ai")

    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def item_matches_topics(title: str, summary: str, topics: list[str]) -> bool:
    """True if text matches any topic. Empty topics → match all."""
    if not topics:
        return True
    haystack = f"{title or ''}\n{summary or ''}".lower()
    haystack = unicodedata.normalize("NFKC", haystack)
    for topic in topics:
        if topic in haystack:
            return True
        pattern = re.compile(rf"(?<!\w){re.escape(topic)}(?!\w)", re.IGNORECASE)
        if pattern.search(haystack):
            return True
    return False
