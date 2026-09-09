from __future__ import annotations

import socket

from telegram.error import BadRequest, Conflict, NetworkError, TimedOut

from bot.telegram_util import (
    is_benign_telegram_error,
    prefer_ipv4,
)


def test_is_benign_telegram_error():
    assert is_benign_telegram_error(
        BadRequest("Query is too old and response timeout expired or query id is invalid")
    )
    assert is_benign_telegram_error(BadRequest("Message is not modified"))
    assert is_benign_telegram_error(TimedOut("timed out"))
    assert is_benign_telegram_error(NetworkError("httpx.ConnectError"))
    assert is_benign_telegram_error(Conflict("terminated by other getUpdates"))
    assert not is_benign_telegram_error(BadRequest("Chat not found"))
    assert not is_benign_telegram_error(RuntimeError("boom"))


def test_prefer_ipv4_filters_aaaa():
    prefer_ipv4()
    prefer_ipv4()  # idempotent
    infos = socket.getaddrinfo("127.0.0.1", 80, type=socket.SOCK_STREAM)
    assert infos
    assert all(info[0] == socket.AF_INET for info in infos)
