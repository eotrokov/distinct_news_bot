from __future__ import annotations

from starlette.testclient import TestClient

from dashboard.app import create_app
from dashboard.config import DashboardSettings


def test_dashboard_is_public(tmp_path):
    settings = DashboardSettings(
        db_path=str(tmp_path / "dash.sqlite3"),
        host="127.0.0.1",
        port=8080,
    )
    app = create_app(settings)
    client = TestClient(app)

    assert client.get("/").status_code == 200
    assert client.get("/users").status_code == 200
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
        host="127.0.0.1",
        port=8080,
    )
    app = create_app(settings)
    client = TestClient(app)

    index = client.get("/")
    assert index.status_code == 200
    assert "Всего workspace" in index.text
    assert ">1<" in index.text

    users = client.get("/users")
    assert users.status_code == 200
    assert "42" in users.text
    assert "@news" not in users.text
    assert 'href="/users?sort=sources_count&amp;dir=desc"' in users.text
    assert 'href="/users?sort=user_id&amp;dir=asc"' in users.text


def test_dashboard_users_sort(tmp_path):
    from bot.db import Database

    db_path = str(tmp_path / "dash-sort.sqlite3")
    db = Database(db_path)
    db.ensure_user(10)
    db.ensure_user(20)
    db.add_source(10, "telegram", "a", "@a")
    db.add_source(20, "telegram", "b1", "@b1")
    db.add_source(20, "telegram", "b2", "@b2")

    settings = DashboardSettings(
        db_path=db_path,
        host="127.0.0.1",
        port=8080,
    )
    app = create_app(settings)
    client = TestClient(app)

    asc = client.get("/users?sort=sources_count&dir=asc")
    assert asc.status_code == 200
    assert asc.text.index(">1</td>") < asc.text.index(">2</td>")
    assert "sort=sources_count&amp;dir=desc" in asc.text

    desc = client.get("/users?sort=sources_count&dir=desc")
    assert desc.status_code == 200
    assert desc.text.index(">2</td>") < desc.text.index(">1</td>")

    by_id = client.get("/users?sort=user_id&dir=asc")
    assert by_id.status_code == 200
    assert by_id.text.index("\n        10\n") < by_id.text.index("\n        20\n")

    bad = client.get("/users?sort=drop_table&dir=sideways")
    assert bad.status_code == 200
    assert "Пользователи" in bad.text
