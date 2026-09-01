from __future__ import annotations

import logging
import sys

from telegram.ext import Application

from bot.config import Settings
from bot.db import Database
from bot.digest import DigestService
from bot.handlers import register_handlers
from bot.jobs import setup_schedule_jobs


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    # httpx logs full request URLs, which include the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def _post_init(app: Application) -> None:
    setup_schedule_jobs(app)
    try:
        from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeDefault

        commands = [
            BotCommand("news", "SEO-дайджест"),
            BotCommand("add", "Добавить источник"),
            BotCommand("sources", "Список источников"),
            BotCommand("schedule", "Авто-сводка"),
            BotCommand("menu", "Меню"),
            BotCommand("help", "Справка"),
        ]
        await app.bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        await app.bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("Failed to set bot commands")


async def _post_shutdown(app: Application) -> None:
    digest: DigestService | None = app.bot_data.get("digest")
    if digest is not None:
        await digest.aclose()


def build_app(settings: Settings) -> Application:
    db = Database(settings.db_path)
    digest = DigestService(db, settings)
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
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
    app.run_polling(
        allowed_updates=[
            "message",
            "callback_query",
            "pre_checkout_query",
            "my_chat_member",
        ]
    )


if __name__ == "__main__":
    main()
