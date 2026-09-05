from __future__ import annotations

from bot.addlist import FolderChannel, parse_telegram_handles
from bot.channel_presets import RssFeed
from bot.db import Database
from bot.fetchers.rss import normalize_rss_url, parse_rss_urls, rss_title_from_url
from bot.fetchers.telegram import normalize_telegram_handle


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


def add_rss_feeds(
    db: Database,
    user_id: int,
    feeds: list[RssFeed] | list[tuple[str, str]] | list[str],
) -> tuple[list[str], list[str]]:
    """Add RSS sources. Returns (added_labels, skipped_labels)."""
    added: list[str] = []
    skipped: list[str] = []
    limits = db.get_entitlement(user_id).limits()
    current = len(db.list_sources(user_id))
    for item in feeds:
        if isinstance(item, RssFeed):
            url, title = item.url, item.title
        elif isinstance(item, tuple):
            url, title = item[0], item[1]
        else:
            url, title = item, ""
        url = normalize_rss_url(url)
        label = title.strip() if title and title.strip() else rss_title_from_url(url)
        if current + len(added) >= limits.max_sources:
            skipped.append(f"{label} (лимит плана {limits.max_sources})")
            continue
        try:
            db.add_source(user_id, "rss", url, label)
            added.append(label)
        except ValueError:
            skipped.append(label)
    return added, skipped


def add_rss_from_text(
    db: Database, user_id: int, text: str
) -> tuple[list[str], list[str]]:
    urls = parse_rss_urls(text)
    if not urls:
        raise ValueError(
            "Не нашёл RSS. Пример: /add rss https://ahrefs.com/blog/feed/"
        )
    return add_rss_feeds(db, user_id, urls)


def add_from_text(
    db: Database, user_id: int, text: str
) -> tuple[list[str], list[str]]:
    """Add Telegram channels and/or RSS feeds found in free-form text."""
    handles = parse_telegram_handles(text)
    urls = parse_rss_urls(text)
    if not handles and not urls:
        raise ValueError(
            "Не нашёл источников. Пример: @bbcnews или "
            "https://ahrefs.com/blog/feed/"
        )
    added: list[str] = []
    skipped: list[str] = []
    if handles:
        a, s = add_telegram_channels(db, user_id, handles)
        added.extend(a)
        skipped.extend(s)
    if urls:
        a, s = add_rss_feeds(db, user_id, urls)
        added.extend(a)
        skipped.extend(s)
    return added, skipped


def add_single_source(
    db: Database,
    user_id: int,
    source_type: str,
    identifier: str,
    title: str,
):
    if source_type not in {"telegram", "rss"}:
        raise ValueError(
            "Поддерживаются публичные Telegram-каналы и RSS-фиды.\n"
            "Примеры: /add @bbcnews\n"
            "/add rss https://ahrefs.com/blog/feed/"
        )
    limits = db.get_entitlement(user_id).limits()
    if len(db.list_sources(user_id)) >= limits.max_sources:
        from bot.plans import is_monetization_enabled

        if is_monetization_enabled():
            raise ValueError(
                f"Лимит источников плана ({limits.max_sources}). "
                "Оформите Pro: /buy pro"
            )
        raise ValueError(f"Лимит источников ({limits.max_sources}).")
    if source_type == "rss":
        identifier = normalize_rss_url(identifier)
        if not title or title.startswith("@"):
            title = rss_title_from_url(identifier)
        return db.add_source(user_id, "rss", identifier, title)
    identifier = normalize_telegram_handle(identifier)
    if not title or title.startswith("@"):
        title = f"@{identifier}"
    return db.add_source(user_id, "telegram", identifier, title)


def format_add_report(
    *,
    folder_title: str | None,
    added: list[str],
    skipped: list[str],
    skipped_private: int = 0,
) -> str:
    lines: list[str] = []
    if folder_title:
        lines.append(f"Набор: {folder_title}")
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
