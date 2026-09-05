from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from bot.db import Database
from dashboard.config import DashboardSettings

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

USER_SORT_COLUMNS = frozenset(
    {
        "user_id",
        "plan",
        "sources_count",
        "topics_count",
        "seen_count",
        "last_digest_at",
        "digests_7d",
        "created_at",
        "schedule",
    }
)
DEFAULT_SORT_BY = "last_digest_at"
DEFAULT_SORT_DIR = "desc"


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _parse_sort(request: Request) -> tuple[str, str]:
    sort_by = str(request.query_params.get("sort") or DEFAULT_SORT_BY)
    if sort_by not in USER_SORT_COLUMNS:
        sort_by = DEFAULT_SORT_BY
    sort_dir = str(request.query_params.get("dir") or DEFAULT_SORT_DIR).lower()
    if sort_dir not in {"asc", "desc"}:
        sort_dir = DEFAULT_SORT_DIR
    return sort_by, sort_dir


def _sort_href(column: str, current_by: str, current_dir: str) -> str:
    if column == current_by:
        next_dir = "asc" if current_dir == "desc" else "desc"
    else:
        # Numbers/dates start descending; ids/plan ascending feels natural.
        next_dir = (
            "asc"
            if column in {"user_id", "plan"}
            else "desc"
        )
    return "/users?" + urlencode({"sort": column, "dir": next_dir})


def _sort_indicator(column: str, current_by: str, current_dir: str) -> str:
    if column != current_by:
        return ""
    return " ↑" if current_dir == "asc" else " ↓"


def create_app(settings: DashboardSettings | None = None) -> Starlette:
    settings = settings or DashboardSettings.from_env()
    db = Database(settings.db_path)
    TEMPLATES.env.filters["fmt_dt"] = _fmt_dt
    TEMPLATES.env.globals["sort_href"] = _sort_href
    TEMPLATES.env.globals["sort_indicator"] = _sort_indicator

    async def index(request: Request) -> HTMLResponse:
        stats = db.get_overview_stats()
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"stats": stats},
        )

    async def users(request: Request) -> HTMLResponse:
        sort_by, sort_dir = _parse_sort(request)
        rows = db.list_users_with_stats(sort_by=sort_by, sort_dir=sort_dir)
        return TEMPLATES.TemplateResponse(
            request,
            "users.html",
            {
                "users": rows,
                "sort_by": sort_by,
                "sort_dir": sort_dir,
            },
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
    app.state.db = db
    app.state.settings = settings
    return app
