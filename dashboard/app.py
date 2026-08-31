from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from bot.db import Database
from dashboard.auth import TokenAuthMiddleware
from dashboard.config import DashboardSettings

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def create_app(settings: DashboardSettings | None = None) -> Starlette:
    settings = settings or DashboardSettings.from_env()
    db = Database(settings.db_path)
    TEMPLATES.env.filters["fmt_dt"] = _fmt_dt

    async def index(request: Request) -> HTMLResponse:
        stats = db.get_overview_stats()
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"stats": stats},
        )

    async def users(request: Request) -> HTMLResponse:
        rows = db.list_users_with_stats()
        return TEMPLATES.TemplateResponse(
            request,
            "users.html",
            {"users": rows},
        )

    async def health(request: Request) -> HTMLResponse:
        return HTMLResponse("ok")

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/users", users),
            Route("/health", health),
        ],
    )
    app.add_middleware(TokenAuthMiddleware, token=settings.token)
    app.state.db = db
    app.state.settings = settings
    return app
