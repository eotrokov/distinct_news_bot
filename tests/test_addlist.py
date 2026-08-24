from __future__ import annotations

import pytest

from bot.addlist import extract_addlist_slug, parse_telegram_handles
from bot.db import Database
from bot.sources_ops import add_telegram_channels, format_add_report


def test_extract_addlist_slug():
    assert (
        extract_addlist_slug("https://t.me/addlist/_0flf9ViWOo0NjNi")
        == "_0flf9ViWOo0NjNi"
    )
    assert extract_addlist_slug("t.me/addlist/AbCdEfGh") == "AbCdEfGh"
    assert extract_addlist_slug("https://t.me/bbcnews") is None


def test_parse_telegram_handles_bulk():
    text = "@meduza https://t.me/bbcnews\nrian_ru, @meduza"
    assert parse_telegram_handles(text) == ["meduza", "bbcnews", "rian_ru"]


def test_parse_skips_addlist_url():
    text = "https://t.me/addlist/_0flf9ViWOo0NjNi @bbcnews"
    assert parse_telegram_handles(text) == ["bbcnews"]


def test_add_telegram_channels_dedupes(tmp_path):
    db = Database(str(tmp_path / "t.sqlite3"))
    uid = 42
    added, skipped = add_telegram_channels(db, uid, ["AlphaChan", "beta_chan"])
    assert added == ["@alphachan", "@beta_chan"]
    assert skipped == []
    added2, skipped2 = add_telegram_channels(db, uid, ["alphachan", "GammaChan"])
    assert added2 == ["@gammachan"]
    assert skipped2 == ["@alphachan"]
    sources = db.list_sources(uid)
    assert {s.identifier for s in sources} == {"alphachan", "beta_chan", "gammachan"}


def test_format_add_report():
    text = format_add_report(
        folder_title="Маркетинг каналы",
        added=["@a", "@b"],
        skipped=["@c"],
    )
    assert "Маркетинг каналы" in text
    assert "Добавлено (2)" in text
    assert "Уже были (1)" in text


@pytest.mark.asyncio
async def test_fetch_addlist_title_parses_og(monkeypatch: pytest.MonkeyPatch):
    from bot import addlist as addlist_mod

    class FakeResp:
        text = '<meta property="og:title" content="Telegram Chats: Маркетинг каналы">'

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str):
            assert "addlist" in url
            return FakeResp()

    monkeypatch.setattr(addlist_mod.httpx, "AsyncClient", FakeClient)
    title = await addlist_mod.fetch_addlist_title(
        "https://t.me/addlist/_0flf9ViWOo0NjNi"
    )
    assert title == "Маркетинг каналы"
