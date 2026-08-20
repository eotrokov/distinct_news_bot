from __future__ import annotations

from bot.addlist import FolderChannel, parse_telegram_handles
from bot.db import Database
from bot.fetchers.ria import RIA_FEEDS
from bot.fetchers.telegram import normalize_telegram_handle


def add_telegram_channels(
    db: Database,
    user_id: int,
    channels: list[FolderChannel] | list[tuple[str, str]] | list[str],
) -> tuple[list[str], list[str]]:
    """Add telegram sources. Returns (added_labels, skipped_labels)."""
    added: list[str] = []
    skipped: list[str] = []
    for item in channels:
        if isinstance(item, FolderChannel):
            handle, title = item.username, item.title or f"@{item.username}"
        elif isinstance(item, tuple):
            handle, title = item[0], item[1]
        else:
            handle, title = item, f"@{item.lstrip('@')}"
        handle = normalize_telegram_handle(handle)
        label = f"@{handle}"
        try:
            db.add_source(user_id, "telegram", handle, title or label)
            added.append(label)
        except ValueError:
            skipped.append(label)
    return added, skipped


def add_telegram_from_text(
    db: Database, user_id: int, text: str
) -> tuple[list[str], list[str]]:
    handles = parse_telegram_handles(text)
    if not handles:
        raise ValueError(
            "Не нашёл каналов. Пример: @bbcnews https://t.me/meduzalive"
        )
    return add_telegram_channels(db, user_id, handles)


def add_single_source(
    db: Database,
    user_id: int,
    source_type: str,
    identifier: str,
    title: str,
):
    if source_type == "telegram":
        identifier = normalize_telegram_handle(identifier)
        if not title or title.startswith("@"):
            title = f"@{identifier}"
    if source_type == "ria" and not (
        identifier.startswith("http://") or identifier.startswith("https://")
    ):
        key = identifier.lower()
        if key not in RIA_FEEDS:
            known = ", ".join(sorted(RIA_FEEDS))
            raise ValueError(f"Лента РИА: {known} или полный URL RSS")
        identifier = key
    return db.add_source(user_id, source_type, identifier, title)


def format_add_report(
    *,
    folder_title: str | None,
    added: list[str],
    skipped: list[str],
    skipped_private: int = 0,
) -> str:
    lines: list[str] = []
    if folder_title:
        lines.append(f"Папка: {folder_title}")
    if added:
        lines.append(f"Добавлено ({len(added)}): " + ", ".join(added))
    else:
        lines.append("Новых каналов не добавлено.")
    if skipped:
        lines.append(f"Уже были ({len(skipped)}): " + ", ".join(skipped))
    if skipped_private:
        lines.append(
            f"Пропущено без @username (приватные): {skipped_private}"
        )
    return "\n".join(lines)
