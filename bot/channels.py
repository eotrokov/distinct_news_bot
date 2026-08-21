from __future__ import annotations

import re

from bot.billing import SourceLimitError, ensure_can_add_source
from bot.config import Settings
from bot.db import Database
from bot.fetchers.telegram import normalize_telegram_handle
from bot.models import Source


def parse_channel_list(raw: str) -> list[str]:
    """Parse many channel handles from free text.

    Accepts: @a @b, commas, newlines, optional ``telegram`` prefix tokens.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError(
            "Пришлите каналы: @channel1 @channel2\n"
            "Можно через запятую или с новой строки."
        )
    # Drop command leftovers.
    text = re.sub(r"(?i)^\s*/add\b", "", text).strip()
    parts = re.split(r"[\s,;]+", text)
    handles: list[str] = []
    seen: set[str] = set()
    for part in parts:
        token = part.strip()
        if not token:
            continue
        if token.lower() in {"telegram", "tg", "channel", "каналы", "канал"}:
            continue
        try:
            handle = normalize_telegram_handle(token).lower()
        except ValueError:
            continue
        if handle in seen:
            continue
        seen.add(handle)
        handles.append(handle)
    if not handles:
        raise ValueError(
            "Не удалось разобрать каналы. Пример:\n"
            "@searchengines @seonews @dev"
        )
    return handles


def add_channels_bulk(
    db: Database,
    settings: Settings,
    user_id: int,
    handles: list[str],
) -> dict[str, object]:
    """Add many Telegram channels. Stops when free+paid slots run out."""
    added: list[Source] = []
    duplicates: list[str] = []
    invalid: list[str] = []
    blocked_by_limit: list[str] = []

    existing = {
        s.identifier.lower()
        for s in db.list_sources(user_id)
        if s.source_type == "telegram"
    }

    for idx, handle in enumerate(handles):
        if handle.lower() in existing:
            duplicates.append(handle)
            continue
        try:
            ensure_can_add_source(db, settings, user_id)
        except SourceLimitError:
            blocked_by_limit.extend(handles[idx:])
            break
        title = f"@{handle}"
        try:
            source = db.add_source(user_id, "telegram", handle, title)
            added.append(source)
            existing.add(handle.lower())
        except ValueError:
            duplicates.append(handle)
            existing.add(handle.lower())

    return {
        "added": added,
        "duplicates": duplicates,
        "invalid": invalid,
        "blocked_by_limit": blocked_by_limit,
    }


def format_bulk_add_result(result: dict[str, object]) -> str:
    added: list[Source] = list(result.get("added") or [])  # type: ignore[arg-type]
    duplicates: list[str] = list(result.get("duplicates") or [])  # type: ignore[arg-type]
    blocked: list[str] = list(result.get("blocked_by_limit") or [])  # type: ignore[arg-type]
    lines: list[str] = []
    if added:
        lines.append(f"Добавлено каналов: {len(added)}")
        for source in added[:20]:
            lines.append(f"• #{source.id} {source.title}")
        if len(added) > 20:
            lines.append(f"… и ещё {len(added) - 20}")
    if duplicates:
        lines.append(
            "Уже были: " + ", ".join(f"@{h}" for h in duplicates[:15])
            + ("…" if len(duplicates) > 15 else "")
        )
    if blocked:
        lines.append(
            f"Не хватило слотов для {len(blocked)} канал(ов). "
            "Оплатите Stars или удалите лишние."
        )
    if not lines:
        lines.append("Ничего не добавлено.")
    return "\n".join(lines)
