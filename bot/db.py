from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from bot.models import Source, SourceType
from bot.plans import TRIAL_DAYS, UserEntitlement
from bot.schedule import UserSchedule


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
                """
            )
            self._ensure_user_schedule_columns(conn)
            self._ensure_user_plan_columns(conn)

    @staticmethod
    def _ensure_user_schedule_columns(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        alterations = [
            ("schedule_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("schedule_hour", "INTEGER NOT NULL DEFAULT 9"),
            ("schedule_minute", "INTEGER NOT NULL DEFAULT 55"),
            ("tz_offset_minutes", "INTEGER NOT NULL DEFAULT 180"),
            ("last_schedule_date", "TEXT"),
        ]
        for name, typedef in alterations:
            if name not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {typedef}")

    @staticmethod
    def _ensure_user_plan_columns(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        alterations = [
            ("plan", "TEXT NOT NULL DEFAULT 'trial'"),
            ("plan_expires_at", "TEXT"),
            ("trial_started_at", "TEXT"),
            ("digests_today", "INTEGER NOT NULL DEFAULT 0"),
            ("digest_day", "TEXT"),
        ]
        for name, typedef in alterations:
            if name not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {typedef}")

    def ensure_user(self, user_id: int) -> None:
        now = _utc_now()
        now_iso = now.isoformat()
        trial_end = (now + timedelta(days=TRIAL_DAYS)).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users(
                    user_id, created_at, plan, trial_started_at, plan_expires_at
                )
                VALUES (?, ?, 'trial', ?, ?)
                ON CONFLICT(user_id) DO NOTHING
                """,
                (user_id, now_iso, now_iso, trial_end),
            )
            # Backfill trial fields for legacy rows.
            conn.execute(
                """
                UPDATE users
                SET trial_started_at = COALESCE(trial_started_at, ?),
                    plan = COALESCE(NULLIF(plan, ''), 'trial'),
                    plan_expires_at = COALESCE(plan_expires_at, ?)
                WHERE user_id = ?
                  AND trial_started_at IS NULL
                """,
                (now_iso, trial_end, user_id),
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

    def clear_seen(self, user_id: int) -> int:
        """Remove all seen fingerprints for a user. Returns deleted row count."""
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM seen_items WHERE user_id = ?",
                (user_id,),
            )
            return int(cur.rowcount)

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

    def get_schedule(self, user_id: int) -> UserSchedule:
        self.ensure_user(user_id)
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT user_id, schedule_enabled, schedule_hour, schedule_minute,
                       tz_offset_minutes, last_schedule_date
                FROM users WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return self._row_to_schedule(row)

    def set_schedule(
        self,
        user_id: int,
        *,
        enabled: bool | None = None,
        hour: int | None = None,
        minute: int | None = None,
        tz_offset_minutes: int | None = None,
    ) -> UserSchedule:
        self.ensure_user(user_id)
        current = self.get_schedule(user_id)
        new_enabled = current.enabled if enabled is None else bool(enabled)
        new_hour = current.hour if hour is None else int(hour)
        new_minute = current.minute if minute is None else int(minute)
        new_tz = (
            current.tz_offset_minutes
            if tz_offset_minutes is None
            else int(tz_offset_minutes)
        )
        if not 0 <= new_hour <= 23:
            raise ValueError("Час должен быть от 0 до 23")
        if not 0 <= new_minute <= 59:
            raise ValueError("Минуты должны быть от 0 до 59")
        if not -12 * 60 <= new_tz <= 14 * 60:
            raise ValueError("Смещение вне диапазона UTC−12…UTC+14")
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET schedule_enabled = ?, schedule_hour = ?, schedule_minute = ?,
                    tz_offset_minutes = ?
                WHERE user_id = ?
                """,
                (1 if new_enabled else 0, new_hour, new_minute, new_tz, user_id),
            )
        return self.get_schedule(user_id)

    def mark_schedule_sent(self, user_id: int, local_date: str) -> None:
        self.ensure_user(user_id)
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET last_schedule_date = ? WHERE user_id = ?",
                (local_date, user_id),
            )

    def list_due_schedules(self, now: datetime | None = None) -> list[UserSchedule]:
        now = now or _utc_now()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id, schedule_enabled, schedule_hour, schedule_minute,
                       tz_offset_minutes, last_schedule_date
                FROM users
                WHERE schedule_enabled = 1
                """
            ).fetchall()
        due: list[UserSchedule] = []
        for row in rows:
            schedule = self._row_to_schedule(row)
            if not schedule.due_now(now):
                continue
            ent = self.get_entitlement(schedule.user_id)
            if not ent.limits(now).allow_schedule:
                continue
            due.append(schedule)
        return due

    def get_entitlement(self, user_id: int) -> UserEntitlement:
        self.ensure_user(user_id)
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT user_id, plan, plan_expires_at, trial_started_at,
                       digests_today, digest_day
                FROM users WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return UserEntitlement(
            user_id=int(row["user_id"]),
            plan=str(row["plan"] or "trial"),
            plan_expires_at=_parse_dt(row["plan_expires_at"]),
            trial_started_at=_parse_dt(row["trial_started_at"]),
            digests_today=int(row["digests_today"] or 0),
            digest_day=row["digest_day"],
        )

    def set_plan(
        self,
        user_id: int,
        plan: str,
        *,
        expires_at: datetime | None = None,
    ) -> UserEntitlement:
        self.ensure_user(user_id)
        stamp = expires_at.astimezone(timezone.utc).isoformat() if expires_at else None
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET plan = ?, plan_expires_at = ?
                WHERE user_id = ?
                """,
                (plan, stamp, user_id),
            )
        return self.get_entitlement(user_id)

    def consume_digest_quota(self, user_id: int) -> tuple[bool, UserEntitlement]:
        """Increment today's digest counter. Returns (allowed, entitlement)."""
        self.ensure_user(user_id)
        today = _utc_now().date().isoformat()
        ent = self.get_entitlement(user_id)
        limits = ent.limits()
        digests_today = ent.digests_today if ent.digest_day == today else 0
        if digests_today >= limits.max_digests_per_day:
            return False, ent
        digests_today += 1
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET digests_today = ?, digest_day = ?
                WHERE user_id = ?
                """,
                (digests_today, today, user_id),
            )
        return True, self.get_entitlement(user_id)

    def count_users(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return int(row["c"])

    def count_sources(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM sources").fetchone()
        return int(row["c"])

    def count_paid_users(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c FROM users
                WHERE plan IN ('pro', 'plus')
                """
            ).fetchone()
        return int(row["c"])

    def delete_user_data(self, user_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))

    @staticmethod
    def _row_to_schedule(row: sqlite3.Row) -> UserSchedule:
        keys = set(row.keys())
        minute = 55
        if "schedule_minute" in keys and row["schedule_minute"] is not None:
            minute = int(row["schedule_minute"])
        return UserSchedule(
            user_id=int(row["user_id"]),
            enabled=bool(row["schedule_enabled"]),
            hour=int(row["schedule_hour"] if row["schedule_hour"] is not None else 9),
            minute=minute,
            tz_offset_minutes=int(
                row["tz_offset_minutes"]
                if row["tz_offset_minutes"] is not None
                else 180
            ),
            last_schedule_date=row["last_schedule_date"],
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
