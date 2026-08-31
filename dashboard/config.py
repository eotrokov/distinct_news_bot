from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


@dataclass(frozen=True)
class DashboardSettings:
    db_path: str
    host: str
    port: int

    @classmethod
    def from_env(cls) -> "DashboardSettings":
        return cls(
            db_path=_env("BOT_DB", "data/bot.sqlite3") or "data/bot.sqlite3",
            host=_env("DASHBOARD_HOST", "0.0.0.0") or "0.0.0.0",
            port=max(1, int(_env("DASHBOARD_PORT", "8080") or "8080")),
        )
