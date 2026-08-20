from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from bot.addlist import FolderChannel, extract_addlist_slug

logger = logging.getLogger(__name__)


class TelegramUserError(RuntimeError):
    """User-facing error for Telegram user-client operations."""


class TelegramUserGateway:
    """Optional Telethon user client for resolving chat-folder (addlist) links.

    Bots cannot call chatlists.checkChatlistInvite — a real user session is required.
    """

    def __init__(
        self,
        api_id: int | None,
        api_hash: str | None,
        session_path: str,
    ) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = session_path
        self._client: Any | None = None
        self._lock = asyncio.Lock()
        self._login: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return bool(self.api_id and self.api_hash)

    def _require_configured(self) -> None:
        if not self.configured:
            raise TelegramUserError(
                "Для ссылок t.me/addlist нужен пользовательский Telegram API.\n"
                "Добавьте TELEGRAM_API_ID и TELEGRAM_API_HASH в .env "
                "(https://my.telegram.org → API development tools), "
                "затем выполните /tg_login +79…"
            )

    async def _get_client(self) -> Any:
        self._require_configured()
        try:
            from telethon import TelegramClient
        except ImportError as exc:  # pragma: no cover
            raise TelegramUserError(
                "Пакет telethon не установлен. Обновите образ бота."
            ) from exc

        if self._client is None:
            Path(self.session_path).parent.mkdir(parents=True, exist_ok=True)
            self._client = TelegramClient(
                self.session_path,
                int(self.api_id),  # type: ignore[arg-type]
                str(self.api_hash),
            )
        if not self._client.is_connected():
            await self._client.connect()
        return self._client

    async def is_authorized(self) -> bool:
        if not self.configured:
            return False
        try:
            client = await self._get_client()
            return bool(await client.is_user_authorized())
        except Exception:  # noqa: BLE001
            logger.exception("Failed to check Telethon authorization")
            return False

    async def auth_status_text(self) -> str:
        if not self.configured:
            return (
                "API не настроен: задайте TELEGRAM_API_ID и TELEGRAM_API_HASH, "
                "затем /tg_login +телефон"
            )
        if await self.is_authorized():
            client = await self._get_client()
            me = await client.get_me()
            name = getattr(me, "username", None) or getattr(me, "first_name", "user")
            return f"Пользовательский вход активен (@{name}). Можно /addlist."
        return "API есть, но входа нет. Выполните /tg_login +телефон"

    async def start_login(self, phone: str) -> str:
        phone = phone.strip().replace(" ", "")
        if not phone.startswith("+") or len(phone) < 8:
            raise TelegramUserError("Укажите телефон в формате +79001234567")
        async with self._lock:
            client = await self._get_client()
            if await client.is_user_authorized():
                me = await client.get_me()
                uname = getattr(me, "username", None) or "ok"
                return f"Уже выполнен вход (@{uname}). Можно сразу /addlist."
            sent = await client.send_code_request(phone)
            self._login = {
                "phone": phone,
                "phone_code_hash": sent.phone_code_hash,
            }
            return (
                "Код отправлен в Telegram (или SMS).\n"
                "Пришлите: /tg_code 12345\n"
                "Если включён облачный пароль — после кода: /tg_password ваш_пароль"
            )

    async def confirm_code(self, code: str) -> str:
        code = code.strip().replace(" ", "")
        if not code:
            raise TelegramUserError("Укажите код: /tg_code 12345")
        async with self._lock:
            if "phone" not in self._login or "phone_code_hash" not in self._login:
                raise TelegramUserError("Сначала /tg_login +телефон")
            client = await self._get_client()
            try:
                from telethon.errors import SessionPasswordNeededError

                await client.sign_in(
                    phone=self._login["phone"],
                    code=code,
                    phone_code_hash=self._login["phone_code_hash"],
                )
            except SessionPasswordNeededError:
                return (
                    "Нужен облачный пароль 2FA.\n"
                    "Пришлите: /tg_password ваш_пароль"
                )
            except Exception as exc:  # noqa: BLE001
                raise TelegramUserError(f"Не удалось войти: {exc}") from exc
            self._login.clear()
            me = await client.get_me()
            uname = getattr(me, "username", None) or getattr(me, "first_name", "user")
            return f"Вход выполнен (@{uname}). Теперь /addlist <ссылка>"

    async def confirm_password(self, password: str) -> str:
        password = password.strip()
        if not password:
            raise TelegramUserError("Укажите пароль: /tg_password …")
        async with self._lock:
            client = await self._get_client()
            try:
                await client.sign_in(password=password)
            except Exception as exc:  # noqa: BLE001
                raise TelegramUserError(f"Пароль не принят: {exc}") from exc
            self._login.clear()
            me = await client.get_me()
            uname = getattr(me, "username", None) or getattr(me, "first_name", "user")
            return f"Вход выполнен (@{uname}). Теперь /addlist <ссылка>"

    async def resolve_addlist(self, url_or_slug: str) -> tuple[str, list[FolderChannel]]:
        slug = extract_addlist_slug(url_or_slug)
        if not slug:
            raise TelegramUserError(
                "Нужна ссылка вида https://t.me/addlist/XXXX или slug папки"
            )
        async with self._lock:
            client = await self._get_client()
            if not await client.is_user_authorized():
                raise TelegramUserError(
                    "Нет пользовательского входа. Сначала /tg_login +телефон"
                )
            try:
                from telethon import functions
                from telethon.tl import types as tl_types
            except ImportError as exc:  # pragma: no cover
                raise TelegramUserError("telethon не установлен") from exc

            try:
                result = await client(
                    functions.chatlists.CheckChatlistInviteRequest(slug=slug)
                )
            except Exception as exc:  # noqa: BLE001
                raise TelegramUserError(
                    f"Не удалось открыть папку addlist: {exc}"
                ) from exc

            title = _folder_title(result) or f"addlist:{slug}"
            channels = _channels_from_invite(result, tl_types)
            if not channels:
                raise TelegramUserError(
                    f"В папке «{title}» нет публичных каналов с @username "
                    "(приватные без username бот читать не может)."
                )
            return title, channels

    async def close(self) -> None:
        if self._client is not None and self._client.is_connected():
            await self._client.disconnect()


def _folder_title(result: Any) -> str:
    title = getattr(result, "title", None)
    if title is None:
        return ""
    # TextWithEntities or plain string depending on layer/telethon version
    text = getattr(title, "text", None)
    if isinstance(text, str):
        return text.strip()
    if isinstance(title, str):
        return title.strip()
    return str(title).strip()


def _channels_from_invite(result: Any, tl_types: Any) -> list[FolderChannel]:
    chats = list(getattr(result, "chats", None) or [])
    channels: list[FolderChannel] = []
    seen: set[str] = set()
    for chat in chats:
        # Prefer broadcast channels; skip plain groups without username.
        username = getattr(chat, "username", None)
        if not username:
            continue
        is_broadcast = bool(getattr(chat, "broadcast", False))
        is_megagroup = bool(getattr(chat, "megagroup", False))
        # Include public channels and public megagroups (both have previews).
        if not (is_broadcast or is_megagroup or isinstance(chat, tl_types.Channel)):
            continue
        key = username.lower()
        if key in seen:
            continue
        seen.add(key)
        title = (getattr(chat, "title", None) or f"@{key}").strip()
        channels.append(FolderChannel(username=key, title=title))
    return channels
