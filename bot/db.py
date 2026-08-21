from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from bot.models import Source, SourceType


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    last_digest_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    source_type TEXT NOT NULL,
                    identifier TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, source_type, identifier),
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS seen_items (
                    user_id INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    url TEXT,
                    title TEXT,
                    seen_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, fingerprint),
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'include',
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, topic),
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS paid_slots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    stars_paid INTEGER NOT NULL,
                    telegram_payment_charge_id TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sources_user
                    ON sources(user_id);
                CREATE INDEX IF NOT EXISTS idx_seen_user_seen_at
                    ON seen_items(user_id, seen_at);
                CREATE INDEX IF NOT EXISTS idx_topics_user
                    ON topics(user_id);
                CREATE INDEX IF NOT EXISTS idx_paid_slots_user_expires
                    ON paid_slots(user_id, expires_at);
                """
            )
            self._migrate_topics_kind(conn)

    def _migrate_topics_kind(self, conn: sqlite3.Connection) -> None:
        cols = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(topics)").fetchall()
        }
        if "kind" not in cols:
            conn.execute(
                "ALTER TABLE topics ADD COLUMN kind TEXT NOT NULL DEFAULT 'include'"
            )

    def ensure_user(self, user_id: int) -> None:
        now = _utc_now().isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users(user_id, created_at)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO NOTHING
                """,
                (user_id, now),
            )

    def get_last_digest_at(self, user_id: int) -> datetime | None:
        self.ensure_user(user_id)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT last_digest_at FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return _parse_dt(row["last_digest_at"] if row else None)

    def set_last_digest_at(self, user_id: int, when: datetime | None = None) -> None:
        self.ensure_user(user_id)
        stamp = (when or _utc_now()).astimezone(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET last_digest_at = ? WHERE user_id = ?",
                (stamp, user_id),
            )

    def reset_last_digest_at(self, user_id: int) -> None:
        self.ensure_user(user_id)
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET last_digest_at = NULL WHERE user_id = ?",
                (user_id,),
            )

    def add_source(
        self,
        user_id: int,
        source_type: SourceType,
        identifier: str,
        title: str,
    ) -> Source:
        self.ensure_user(user_id)
        now = _utc_now().isoformat()
        with self.connect() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO sources(user_id, source_type, identifier, title, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, source_type, identifier, title, now),
                )
                source_id = int(cur.lastrowid)
            except sqlite3.IntegrityError as exc:
                raise ValueError("Источник уже добавлен") from exc

            row = conn.execute(
                "SELECT * FROM sources WHERE id = ?",
                (source_id,),
            ).fetchone()
        return self._row_to_source(row)

    def remove_source(self, user_id: int, source_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM sources WHERE id = ? AND user_id = ?",
                (source_id, user_id),
            )
            return cur.rowcount > 0

    def list_sources(self, user_id: int) -> list[Source]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sources
                WHERE user_id = ?
                ORDER BY id
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_source(row) for row in rows]

    def count_sources(self, user_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM sources WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row["c"] if row else 0)

    def count_active_paid_slots(self, user_id: int) -> int:
        now = _utc_now().isoformat()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM paid_slots
                WHERE user_id = ? AND expires_at > ?
                """,
                (user_id, now),
            ).fetchone()
        return int(row["c"] if row else 0)

    def source_limit(self, user_id: int, free_limit: int) -> int:
        return max(0, int(free_limit)) + self.count_active_paid_slots(user_id)

    def list_active_sources(
        self, user_id: int, free_limit: int
    ) -> tuple[list[Source], list[Source]]:
        """Return (fetchable, paused_over_limit) sources."""
        sources = self.list_sources(user_id)
        limit = self.source_limit(user_id, free_limit)
        return sources[:limit], sources[limit:]

    def add_paid_slot(
        self,
        user_id: int,
        stars_paid: int,
        days: int,
        telegram_payment_charge_id: str | None = None,
    ) -> tuple[datetime, datetime]:
        from datetime import timedelta

        self.ensure_user(user_id)
        created = _utc_now()
        expires = created + timedelta(days=max(1, int(days)))
        with self.connect() as conn:
            if telegram_payment_charge_id:
                existing = conn.execute(
                    """
                    SELECT created_at, expires_at FROM paid_slots
                    WHERE telegram_payment_charge_id = ?
                    LIMIT 1
                    """,
                    (telegram_payment_charge_id,),
                ).fetchone()
                if existing:
                    return (
                        _parse_dt(existing["created_at"]) or created,
                        _parse_dt(existing["expires_at"]) or expires,
                    )
            conn.execute(
                """
                INSERT INTO paid_slots(
                    user_id, stars_paid, telegram_payment_charge_id,
                    created_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    int(stars_paid),
                    telegram_payment_charge_id,
                    created.isoformat(),
                    expires.isoformat(),
                ),
            )
        return created, expires

    def latest_paid_slot_expiry(self, user_id: int) -> datetime | None:
        now = _utc_now().isoformat()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT expires_at FROM paid_slots
                WHERE user_id = ? AND expires_at > ?
                ORDER BY expires_at DESC
                LIMIT 1
                """,
                (user_id, now),
            ).fetchone()
        return _parse_dt(row["expires_at"] if row else None)

    def mark_seen(
        self,
        user_id: int,
        fingerprints: list[tuple[str, str, str]],
    ) -> None:
        """fingerprints: list of (fingerprint, url, title)."""
        if not fingerprints:
            return
        now = _utc_now().isoformat()
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO seen_items(user_id, fingerprint, url, title, seen_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, fingerprint) DO NOTHING
                """,
                [
                    (user_id, fp, url, title, now)
                    for fp, url, title in fingerprints
                ],
            )

    def filter_unseen(
        self, user_id: int, fingerprints: list[str]
    ) -> set[str]:
        if not fingerprints:
            return set()
        placeholders = ",".join("?" for _ in fingerprints)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT fingerprint FROM seen_items
                WHERE user_id = ? AND fingerprint IN ({placeholders})
                """,
                (user_id, *fingerprints),
            ).fetchall()
        seen = {row["fingerprint"] for row in rows}
        return set(fingerprints) - seen

    def cleanup_seen(self, user_id: int, keep_days: int = 30) -> None:
        cutoff = datetime.now(timezone.utc).timestamp() - keep_days * 86400
        cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM seen_items WHERE user_id = ? AND seen_at < ?",
                (user_id, cutoff_iso),
            )

    def add_topic(
        self, user_id: int, topic: str, kind: str = "include"
    ) -> tuple[str, str]:
        self.ensure_user(user_id)
        kind = "exclude" if kind == "exclude" else "include"
        now = _utc_now().isoformat()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id, kind FROM topics WHERE user_id = ? AND topic = ?",
                (user_id, topic),
            ).fetchone()
            if existing:
                if str(existing["kind"]) == kind:
                    raise ValueError(f"Тема уже добавлена: {topic}")
                conn.execute(
                    "UPDATE topics SET kind = ? WHERE id = ?",
                    (kind, int(existing["id"])),
                )
                return topic, kind
            try:
                conn.execute(
                    """
                    INSERT INTO topics(user_id, topic, kind, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, topic, kind, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Тема уже добавлена: {topic}") from exc
        return topic, kind

    def remove_topic(self, user_id: int, topic: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM topics WHERE user_id = ? AND topic = ?",
                (user_id, topic),
            )
            return cur.rowcount > 0

    def remove_topic_by_id(self, user_id: int, topic_id: int) -> tuple[str, str] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT topic, kind FROM topics WHERE id = ? AND user_id = ?",
                (topic_id, user_id),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "DELETE FROM topics WHERE id = ? AND user_id = ?",
                (topic_id, user_id),
            )
            return str(row["topic"]), str(row["kind"] or "include")

    def clear_topics(self, user_id: int, kind: str | None = None) -> int:
        with self.connect() as conn:
            if kind in {"include", "exclude"}:
                cur = conn.execute(
                    "DELETE FROM topics WHERE user_id = ? AND kind = ?",
                    (user_id, kind),
                )
            else:
                cur = conn.execute(
                    "DELETE FROM topics WHERE user_id = ?",
                    (user_id,),
                )
            return int(cur.rowcount)

    def list_topics(self, user_id: int, kind: str | None = None) -> list[str]:
        return [t for _, t, _ in self.list_topic_rows(user_id, kind=kind)]

    def list_include_topics(self, user_id: int) -> list[str]:
        return self.list_topics(user_id, kind="include")

    def list_exclude_topics(self, user_id: int) -> list[str]:
        return self.list_topics(user_id, kind="exclude")

    def list_topic_rows(
        self, user_id: int, kind: str | None = None
    ) -> list[tuple[int, str, str]]:
        with self.connect() as conn:
            if kind in {"include", "exclude"}:
                rows = conn.execute(
                    """
                    SELECT id, topic, kind FROM topics
                    WHERE user_id = ? AND kind = ?
                    ORDER BY topic
                    """,
                    (user_id, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, topic, kind FROM topics
                    WHERE user_id = ?
                    ORDER BY kind DESC, topic
                    """,
                    (user_id,),
                ).fetchall()
        return [
            (int(row["id"]), str(row["topic"]), str(row["kind"] or "include"))
            for row in rows
        ]

    @staticmethod
    def _row_to_source(row: sqlite3.Row) -> Source:
        return Source(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            source_type=row["source_type"],  # type: ignore[arg-type]
            identifier=row["identifier"],
            title=row["title"],
            created_at=_parse_dt(row["created_at"]) or _utc_now(),
        )
