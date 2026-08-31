from __future__ import annotations

from starlette.testclient import TestClient

from dashboard.app import create_app
from dashboard.config import DashboardSettings


def test_dashboard_requires_token(tmp_path):
    db_path = str(tmp_path / "dash.sqlite3")
    settings = DashboardSettings(
        db_path=db_path,
        token="secret-token",
        host="127.0.0.1",
        port=8080,
    )
    app = create_app(settings)
    client = TestClient(app)

    assert client.get("/").status_code == 401
    assert client.get("/users").status_code == 401
    assert client.get("/health").status_code == 200
    assert client.get("/health").text == "ok"


def test_dashboard_shows_stats(tmp_path):
    from bot.db import Database

    db_path = str(tmp_path / "dash.sqlite3")
    db = Database(db_path)
    db.ensure_user(42)
    db.add_source(42, "telegram", "news", "@news")
    db.log_digest_event(42, 2, trigger="manual")

    settings = DashboardSettings(
        db_path=db_path,
        token="secret-token",
        host="127.0.0.1",
        port=8080,
    )
    app = create_app(settings)
    client = TestClient(app)
    headers = {"Authorization": "Bearer secret-token"}

    index = client.get("/", headers=headers)
    assert index.status_code == 200
    assert "Всего workspace" in index.text
    assert ">1<" in index.text

    users = client.get("/users", headers=headers)
    assert users.status_code == 200
    assert "42" in users.text
    assert "@news" not in users.text

    query = client.get("/?token=secret-token")
    assert query.status_code == 200
