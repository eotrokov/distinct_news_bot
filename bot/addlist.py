from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

_ADDLIST_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/addlist/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_HANDLE_TOKEN_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?@?([A-Za-z0-9_]{4,})"
    r"|^@?([A-Za-z0-9_]{4,})$",
    re.IGNORECASE,
)
_OG_TITLE_RE = re.compile(
    r'property="og:title"\s+content="([^"]*)"',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FolderChannel:
    username: str
    title: str


def extract_addlist_slug(value: str) -> str | None:
    """Return addlist slug from URL/text, or None."""
    text = value.strip()
    match = _ADDLIST_RE.search(text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{8,}", text) and "://" not in text:
        return text
    return None


def parse_telegram_handles(text: str) -> list[str]:
    """Parse one or many channel handles from free text.

    Accepts spaces, commas, newlines, @handles and t.me links.
    Skips addlist URLs (handled separately).
    """
    handles: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\s,;]+", text.strip()):
        token = raw.strip()
        if not token:
            continue
        if _ADDLIST_RE.search(token):
            continue
        match = _HANDLE_TOKEN_RE.match(token)
        if not match:
            continue
        handle = (match.group(1) or match.group(2) or "").lstrip("@")
        if not handle or handle.lower() == "addlist":
            continue
        key = handle.lower()
        if key in seen:
            continue
        seen.add(key)
        handles.append(key)
    return handles


async def fetch_addlist_title(url_or_slug: str, timeout: float = 20.0) -> str:
    """Fetch public folder title from t.me/addlist page (no login)."""
    slug = extract_addlist_slug(url_or_slug)
    if not slug:
        raise ValueError(
            "Нужна ссылка вида https://t.me/addlist/XXXX"
        )
    url = f"https://t.me/addlist/{slug}"
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "distinct-news-bot/0.1"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
    except httpx.HTTPError as exc:
        raise ValueError(f"Не удалось открыть папку: {url}") from exc

    match = _OG_TITLE_RE.search(html)
    if not match:
        return f"addlist:{slug}"
    title = match.group(1).strip()
    # "Telegram Chats: SEO каналы" → "SEO каналы"
    prefix = "Telegram Chats:"
    if title.startswith(prefix):
        title = title[len(prefix) :].strip()
    return title or f"addlist:{slug}"
