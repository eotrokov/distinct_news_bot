from __future__ import annotations

import pytest

from bot.http_util import HttpService


@pytest.mark.asyncio
async def test_http_service_caches(monkeypatch):
    service = HttpService(timeout=5, concurrency=2, cache_ttl_seconds=60, max_retries=0)
    calls = {"n": 0}

    class FakeResponse:
        text = "hello"

        def raise_for_status(self) -> None:
            return None

    async def fake_get(url: str):
        calls["n"] += 1
        return FakeResponse()

    monkeypatch.setattr(service._client, "get", fake_get)
    try:
        assert await service.get_text("https://example.com/a") == "hello"
        assert await service.get_text("https://example.com/a") == "hello"
        assert calls["n"] == 1
    finally:
        await service.aclose()
