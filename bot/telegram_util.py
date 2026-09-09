"""Small Telegram helpers: quiet callback answers and noisy-error filtering."""

from __future__ import annotations

import logging
import socket

from telegram import CallbackQuery
from telegram.error import BadRequest, Conflict, NetworkError, TimedOut
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

_BENIGN_BADREQUEST = (
    "query is too old",
    "query id is invalid",
    "response timeout expired",
    "message is not modified",
    "message to edit not found",
    "message can't be edited",
    "button_data_invalid",
)


def is_benign_telegram_error(exc: BaseException) -> bool:
    # BadRequest subclasses NetworkError in PTB — check it first.
    if isinstance(exc, BadRequest):
        msg = str(exc).lower()
        return any(part in msg for part in _BENIGN_BADREQUEST)
    if isinstance(exc, Conflict):
        # Another getUpdates instance briefly overlapping during deploy.
        return True
    if isinstance(exc, TimedOut):
        return True
    if isinstance(exc, NetworkError):
        return True
    return False


async def safe_answer_callback(
    query: CallbackQuery | None,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    """Answer a callback query without spamming logs on stale/duplicate answers."""
    if query is None:
        return
    try:
        if text is None:
            await query.answer()
        else:
            await query.answer(text, show_alert=show_alert)
    except BadRequest as exc:
        if is_benign_telegram_error(exc):
            logger.debug("Ignoring callback answer BadRequest: %s", exc)
            return
        raise


async def on_telegram_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global PTB error handler — keep operational logs clean."""
    err = context.error
    if err is None:
        return
    if is_benign_telegram_error(err):
        logger.warning("Telegram soft error: %s", err)
        return
    logger.exception("Unhandled bot error", exc_info=err)


def prefer_ipv4() -> None:
    """Prefer IPv4 DNS results.

    Some VPS hosts resolve api.telegram.org to broken IPv6 routes (same class of
    issue as Docker Hub IPv6 failures). Filtering AAAA lookups avoids ConnectError
    spam / crash loops on bootstrap.
    """
    if getattr(socket, "_distinct_news_ipv4_patched", False):
        return
    original = socket.getaddrinfo

    def getaddrinfo_ipv4_first(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        infos = original(host, port, family, type, proto, flags)
        if family not in (0, socket.AF_UNSPEC):
            return infos
        v4 = [info for info in infos if info[0] == socket.AF_INET]
        return v4 or infos

    socket.getaddrinfo = getaddrinfo_ipv4_first  # type: ignore[assignment]
    socket._distinct_news_ipv4_patched = True  # type: ignore[attr-defined]
    logger.info("Preferring IPv4 for outbound DNS lookups")
