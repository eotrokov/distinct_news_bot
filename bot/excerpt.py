from __future__ import annotations

import re
from html import escape

from bot.models import NewsItem

_SPACE_RE = re.compile(r"\s+")
SUMMARY_LEN = 200


def _clip(text: str, limit: int) -> str:
    text = _SPACE_RE.sub(" ", text.replace("\n", " ")).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return (cut or text[: limit - 1]).rstrip(".,;:") + "…"


def build_excerpt(item: NewsItem, limit: int = SUMMARY_LEN) -> str:
    """Short summary text for the digest scroll."""
    title = (item.title or "").strip()
    summary = (item.summary or "").strip()
    if not summary:
        return _clip(title, limit)
    if summary.lower().startswith(title.lower()):
        return _clip(summary, limit)
    return _clip(summary, limit)


def format_item_block(idx: int, item: NewsItem) -> str:
    """One post card in the digest портянка (HTML)."""
    when = ""
    if item.published_at:
        when = item.published_at.strftime("%d.%m %H:%M")

    source = escape(item.source_name or item.source_type)
    title = escape((item.title or "").strip() or "Без заголовка")
    summary_raw = (item.summary or "").strip()
    summary_line = ""
    if summary_raw:
        # Avoid repeating the title when summary starts with it.
        body = summary_raw
        if body.lower().startswith((item.title or "").strip().lower()):
            body = body[len((item.title or "").strip()) :].lstrip(" .—–-\n")
        if body:
            summary_line = f"📝 {escape(_clip(body, SUMMARY_LEN))}"

    head = f"<b>{idx}. {source}</b>"
    if when:
        head += f" · {when}"

    lines = [head, f"📌 {title}"]
    if summary_line:
        lines.append(summary_line)
    if item.url:
        lines.append(f'🔗 <a href="{escape(item.url, quote=True)}">открыть пост</a>')
    return "\n".join(lines) + "\n"
