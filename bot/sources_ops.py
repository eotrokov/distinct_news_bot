from __future__ import annotations

from __future__ import annotations

from urllib.parse import urlparse

from bot.addlist import FolderChannel, parse_telegram_handles
from bot.channel_presets import PresetItem
from bot.db import Database
from bot.fetchers.telegram import normalize_telegram_handle


def add_preset_sources(
    db: Database,
    user_id: int,
    channels: list[FolderChannel | PresetItem] | tuple[FolderChannel | PresetItem, ...],
) -> tuple[list[str], list[str]]:
    """Add preset sources (Telegram or RSS). Returns (added_labels, skipped_labels)."""
    added: list[str] = []
    skipped: list[str] = []
    limits = db.get_entitlement(user_id).limits()
    current = len(db.list_sources(user_id))
    for item in channels:
        if isinstance(item, FolderChannel):
            source_type = "telegram"
            handle = normalize_telegram_handle(item.username)
            ident = handle
            label = f"@{handle}"
            title = item.title or label
        elif isinstance(item, PresetItem):
            source_type = item.source_type
            ident = item.identifier.strip()
            label = item.title or ident
            title = item.title or ident
            if source_type == "telegram":
                handle = normalize_telegram_handle(ident)
                ident = handle
                label = f"@{handle}"
                title = item.title or label
        else:
            continue

        if current + len(added) >= limits.max_sources:
            skipped.append(f"{label} (лимит плана {limits.max_sources})")
            continue
        try:
            db.add_source(user_id, source_type, ident, title)  # type: ignore[arg-type]
            added.append(label)
        except ValueError:
            skipped.append(label)
    return added, skipped


def add_telegram_channels(
    db: Database,
    user_id: int,
    channels: list[FolderChannel] | list[tuple[str, str]] | list[str],
) -> tuple[list[str], list[str]]:
    """Add telegram sources. Returns (added_labels, skipped_labels)."""
    added: list[str] = []
    skipped: list[str] = []
    limits = db.get_entitlement(user_id).limits()
    current = len(db.list_sources(user_id))
    for item in channels:
        if isinstance(item, FolderChannel):
            handle, title = item.username, item.title or f"@{item.username}"
        elif isinstance(item, tuple):
            handle, title = item[0], item[1]
        else:
            handle, title = item, f"@{item.lstrip('@')}"
        handle = normalize_telegram_handle(handle)
        label = f"@{handle}"
        if current + len(added) >= limits.max_sources:
            skipped.append(f"{label} (лимит плана {limits.max_sources})")
            continue
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
    if source_type not in {"telegram", "rss"}:
        raise ValueError(
            "Поддерживаются Telegram-каналы и RSS-ленты.\n"
            "Пример: /add @bbcnews или /add rss https://site.com/feed/"
        )
    limits = db.get_entitlement(user_id).limits()
    if len(db.list_sources(user_id)) >= limits.max_sources:
        raise ValueError(
            f"Лимит источников плана ({limits.max_sources}). "
            "Оформите Pro: /buy pro"
        )
    if source_type == "telegram":
        identifier = normalize_telegram_handle(identifier)
        if not title or title.startswith("@"):
            title = f"@{identifier}"
    elif source_type == "rss":
        identifier = identifier.strip()
        if not identifier.startswith(("http://", "https://")):
            identifier = f"https://{identifier}"
        if not title:
            parsed = urlparse(identifier)
            title = parsed.netloc or identifier
    return db.add_source(user_id, source_type, identifier, title)  # type: ignore[arg-type]


def format_add_report(
    *,
    folder_title: str | None,
    added: list[str],
    skipped: list[str],
    skipped_private: int = 0,
) -> str:
    lines: list[str] = []
    if folder_title:
        lines.append(f"Набор/Папка: {folder_title}")
    if added:
        lines.append(f"Добавлено ({len(added)}): " + ", ".join(added))
    else:
        lines.append("Новых источников не добавлено.")
    if skipped:
        lines.append(f"Уже были ({len(skipped)}): " + ", ".join(skipped))
    if skipped_private:
        lines.append(
            f"Пропущено без @username (приватные): {skipped_private}"
        )
    return "\n".join(lines)

