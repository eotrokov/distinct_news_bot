from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {"User-Agent": "distinct-news-bot/0.1"}


class HttpService:
    """Shared httpx client with concurrency limit, retries, and short TTL cache."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        concurrency: int = 5,
        cache_ttl_seconds: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        self.timeout = timeout
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_retries = max_retries
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
        )
        self._cache: dict[str, tuple[float, str]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    def clear_cache(self) -> None:
        self._cache.clear()

    async def get_text(
        self,
        url: str,
        *,
        use_cache: bool = True,
        follow_redirects: bool = True,
    ) -> str:
        if use_cache:
            cached = self._cache.get(url)
            if cached and cached[0] > time.monotonic():
                return cached[1]

        last_exc: Exception | None = None
        async with self._sem:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await self._client.get(
                        url, follow_redirects=follow_redirects
                    )
                    response.raise_for_status()
                    text = response.text
                    if use_cache and self.cache_ttl_seconds > 0:
                        self._cache[url] = (
                            time.monotonic() + self.cache_ttl_seconds,
                            text,
                        )
                    return text
                except httpx.HTTPError as exc:
                    last_exc = exc
                    if attempt >= self.max_retries:
                        break
                    await asyncio.sleep(0.4 * (attempt + 1))
                    logger.warning(
                        "HTTP retry %s/%s for %s: %s",
                        attempt + 1,
                        self.max_retries,
                        url,
                        exc,
                    )
        assert last_exc is not None
        raise last_exc
