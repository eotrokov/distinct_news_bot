from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from bot.models import Feedback, Source, SourceType


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
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, topic),
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sources_user
                    ON sources(user_id);
                CREATE INDEX IF NOT EXISTS idx_seen_user_seen_at
                    ON seen_items(user_id, seen_at);
                CREATE INDEX IF NOT EXISTS idx_topics_user
                    ON topics(user_id);

                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_feedback_status
                    ON feedback(status);
                """
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

    def add_topic(self, user_id: int, topic: str) -> str:
        self.ensure_user(user_id)
        now = _utc_now().isoformat()
        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO topics(user_id, topic, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, topic, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Тема уже добавлена: {topic}") from exc
        return topic

    def remove_topic(self, user_id: int, topic: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM topics WHERE user_id = ? AND topic = ?",
                (user_id, topic),
            )
            return cur.rowcount > 0

    def remove_topic_by_id(self, user_id: int, topic_id: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT topic FROM topics WHERE id = ? AND user_id = ?",
                (topic_id, user_id),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "DELETE FROM topics WHERE id = ? AND user_id = ?",
                (topic_id, user_id),
            )
            return str(row["topic"])

    def clear_topics(self, user_id: int) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM topics WHERE user_id = ?",
                (user_id,),
            )
            return int(cur.rowcount)

    def list_topics(self, user_id: int) -> list[str]:
        return [t for _, t in self.list_topic_rows(user_id)]

    def list_topic_rows(self, user_id: int) -> list[tuple[int, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, topic FROM topics
                WHERE user_id = ?
                ORDER BY topic
                """,
                (user_id,),
            ).fetchall()
        return [(int(row["id"]), str(row["topic"])) for row in rows]

    def add_feedback(self, user_id: int, username: str, text: str) -> Feedback:
        self.ensure_user(user_id)
        now = _utc_now().isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO feedback(user_id, username, text, status, created_at)
                VALUES (?, ?, ?, 'new', ?)
                """,
                (user_id, username, text, now),
            )
            row = conn.execute(
                "SELECT * FROM feedback WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        return self._row_to_feedback(row)

    def list_feedback(
        self, status: str | None = None, limit: int = 50
    ) -> list[Feedback]:
        with self.connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM feedback WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM feedback ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_feedback(r) for r in rows]

    def get_feedback(self, feedback_id: int) -> Feedback | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM feedback WHERE id = ?", (feedback_id,)
            ).fetchone()
        return self._row_to_feedback(row) if row else None

    def update_feedback_status(self, feedback_id: int, status: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE feedback SET status = ? WHERE id = ?",
                (status, feedback_id),
            )
            return cur.rowcount > 0

    def count_feedback(self, status: str | None = None) -> int:
        with self.connect() as conn:
            if status:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM feedback WHERE status = ?",
                    (status,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM feedback"
                ).fetchone()
        return int(row["cnt"]) if row else 0

    @staticmethod
    def _row_to_feedback(row: sqlite3.Row) -> Feedback:
        return Feedback(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            username=row["username"] or "",
            text=row["text"],
            created_at=_parse_dt(row["created_at"]) or _utc_now(),
            status=row["status"],
        )

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
