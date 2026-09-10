from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest

from bot.jobs import (
    _IN_FLIGHT,
    _send_digest_message,
    _send_scheduled_digest,
    deliver_digest_to_user,
)
from bot.schedule import UserSchedule


def _schedule(user_id: int = 42) -> UserSchedule:
    return UserSchedule(
        user_id=user_id,
        enabled=True,
        hour=9,
        minute=55,
        tz_offset_minutes=180,
        last_schedule_date=None,
    )


def _context(*, bot=None, db=None, digest=None) -> SimpleNamespace:
    bot = bot or AsyncMock()
    db = db or MagicMock()
    digest = digest or MagicMock()
    app = SimpleNamespace(
        bot_data={"db": db, "digest": digest, "digest_sessions": {}}
    )
    return SimpleNamespace(bot=bot, application=app)


@pytest.mark.asyncio
async def test_send_digest_message_falls_back_on_html_parse_error():
    bot = AsyncMock()
    bot.send_message.side_effect = [
        BadRequest("Can't parse entities: unsupported start tag"),
        None,
    ]
    context = _context(bot=bot)
    await _send_digest_message(
        context,
        chat_id=1,
        text="<b>Hello</b> & more",
        reply_markup=None,
    )
    assert bot.send_message.await_count == 2
    second = bot.send_message.await_args_list[1]
    assert second.kwargs["text"] == "Hello & more"
    assert "parse_mode" not in second.kwargs


@pytest.mark.asyncio
async def test_schedule_marks_sent_only_after_successful_send():
    _IN_FLIGHT.clear()
    bot = AsyncMock()
    db = MagicMock()
    db.consume_digest_quota.return_value = (True, MagicMock())
    digest = MagicMock()
    digest.collect_for_user = AsyncMock(
        return_value=([], [], [], 1, {"categories": {}, "stats": {}})
    )
    digest.format_digest.return_value = ["пусто"]
    context = _context(bot=bot, db=db, digest=digest)

    await _send_scheduled_digest(context, _schedule())

    db.mark_schedule_sent.assert_called_once()
    bot.send_message.assert_awaited()
    digest.mark_digest_delivered.assert_called_once()
    assert _IN_FLIGHT == set()


@pytest.mark.asyncio
async def test_schedule_does_not_mark_sent_when_telegram_send_fails():
    _IN_FLIGHT.clear()
    bot = AsyncMock()
    bot.send_message.side_effect = BadRequest("Forbidden: bot was blocked by the user")
    db = MagicMock()
    db.consume_digest_quota.return_value = (True, MagicMock())
    digest = MagicMock()
    digest.collect_for_user = AsyncMock(
        return_value=([], [], [], 1, {"categories": {}, "stats": {}})
    )
    digest.format_digest.return_value = ["текст"]
    context = _context(bot=bot, db=db, digest=digest)

    await _send_scheduled_digest(context, _schedule(7))

    db.mark_schedule_sent.assert_not_called()
    digest.mark_digest_delivered.assert_not_called()
    assert _IN_FLIGHT == set()


@pytest.mark.asyncio
async def test_schedule_skips_when_already_in_flight():
    _IN_FLIGHT.clear()
    _IN_FLIGHT.add(99)
    bot = AsyncMock()
    db = MagicMock()
    context = _context(bot=bot, db=db)

    await _send_scheduled_digest(context, _schedule(99))

    db.mark_schedule_sent.assert_not_called()
    bot.send_message.assert_not_awaited()
    _IN_FLIGHT.clear()


@pytest.mark.asyncio
async def test_deliver_marks_delivered_after_send():
    bot = AsyncMock()
    db = MagicMock()
    db.consume_digest_quota.return_value = (True, MagicMock())
    digest = MagicMock()
    digest.collect_for_user = AsyncMock(
        return_value=([], [], [], 1, {"categories": {}, "stats": {}})
    )
    digest.format_digest.return_value = ["ok"]
    context = _context(bot=bot, db=db, digest=digest)

    # Fail first HTML attempt? no — succeed
    order: list[str] = []

    async def send_ok(**kwargs):
        order.append("send")

    def mark(*args, **kwargs):
        order.append("mark")

    bot.send_message.side_effect = send_ok
    digest.mark_digest_delivered.side_effect = mark

    ok = await deliver_digest_to_user(context, 5, days=1)
    assert ok is True
    assert order == ["send", "mark"]
