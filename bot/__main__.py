from __future__ import annotations

import logging
import sys

from telegram.ext import Application

from bot.config import Settings
from bot.db import Database
from bot.digest import DigestService
from bot.handlers import register_handlers


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    # httpx logs full request URLs, which include the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_app(settings: Settings) -> Application:
    db = Database(settings.db_path)
    digest = DigestService(db, settings)
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )
    app.bot_data["db"] = db
    app.bot_data["digest"] = digest
    app.bot_data["settings"] = settings
    register_handlers(app)
    return app


def main() -> None:
    settings = Settings.from_env()
    setup_logging(settings.log_level)
    app = build_app(settings)
    logging.getLogger(__name__).info("Starting distinct-news-bot")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
