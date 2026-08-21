from __future__ import annotations

import re
from html import escape

from bot.models import NewsItem

_SPACE_RE = re.compile(r"\s+")
EXCERPT_LEN = 320


def build_excerpt(item: NewsItem, limit: int = EXCERPT_LEN) -> str:
    """Readable short text for the digest scroll (выжимка)."""
    title = (item.title or "").strip()
    summary = (item.summary or "").strip()
    summary = _SPACE_RE.sub(" ", summary.replace("\n", " ")).strip()

    if not summary:
        body = title
    elif not title:
        body = summary
    elif summary.lower().startswith(title.lower()):
        body = summary
    elif title.lower() in summary.lower()[: max(len(title) + 40, 80)]:
        body = summary
    else:
        # Keep both when summary is a different blurb (typical for RSS).
        body = f"{title}. {summary}"

    body = _SPACE_RE.sub(" ", body).strip()
    if len(body) <= limit:
        return body
    cut = body[: limit - 1].rsplit(" ", 1)[0]
    return (cut or body[: limit - 1]).rstrip(".,;:") + "…"


def format_item_block(idx: int, item: NewsItem) -> str:
    """One post card in the digest портянка (HTML)."""
    when = ""
    if item.published_at:
        when = item.published_at.strftime("%d.%m %H:%M")

    source = escape(item.source_name or item.source_type)
    head = f"<b>{idx}. {source}</b>"
    if when:
        head += f" · {when}"

    excerpt = escape(build_excerpt(item))
    lines = [head, excerpt]
    if item.url:
        lines.append(f'<a href="{escape(item.url, quote=True)}">открыть пост →</a>')
    return "\n".join(lines) + "\n"
