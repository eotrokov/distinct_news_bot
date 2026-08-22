from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from bot import ai_summarize
from bot.ai_summarize import (
    ai_summary_active,
    build_prompt,
    call_gemini,
    enrich_items,
    merge_items_into_analysis,
    parse_gemini_response,
)
from bot.config import Settings
from bot.models import NewsItem


def _settings(**overrides) -> Settings:
    base = dict(
        telegram_bot_token="x",
        db_path=":memory:",
        log_level="INFO",
        digest_limit=30,
        digest_page_size=10,
        fetch_timeout_seconds=5.0,
        rsshub_base_url=None,
        default_digest_days=3,
        default_lookback_hours=72,
        free_source_limit=20,
        stars_per_extra_source=10,
        paid_slot_days=30,
        summary_max_sentences=3,
        weekly_top_limit=10,
        weekly_digest_hour_utc=9,
        weekly_digest_weekday=0,
        ai_summary_enabled=True,
        ai_provider="gemini",
        ai_api_key="gemini_test_key",
        ai_model="gemini-2.0-flash",
        ai_max_concurrent=2,
        ai_timeout_seconds=5.0,
    )
    base.update(overrides)
    return Settings(**base)


def _item(**overrides) -> NewsItem:
    base = dict(
        title="Google запустил spam update",
        url="https://t.me/example/1",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_type="telegram",
        source_name="@test",
        summary="Старая rule-based сводка.",
        body="Google официально объявил spam update алгоритма ранжирования.",
        external_id="example/1",
    )
    base.update(overrides)
    return NewsItem(**base)


def test_ai_summary_active_requires_key():
    assert ai_summary_active(_settings()) is True
    assert ai_summary_active(_settings(ai_api_key=None)) is False
    assert ai_summary_active(_settings(ai_summary_enabled=False)) is False


def test_build_prompt_includes_title_and_body():
    prompt = build_prompt(_item(), max_sentences=3)
    assert "Google запустил spam update" in prompt
    assert "Google официально объявил" in prompt
    assert "3 информативных предложения" in prompt


def test_parse_gemini_response_extracts_content():
    payload = {
        "candidates": [
            {"content": {"parts": [{"text": "  Новая AI-сводка поста.  "}]}}
        ]
    }
    assert parse_gemini_response(payload) == "Новая AI-сводка поста."


@pytest.mark.asyncio
async def test_call_gemini_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "generateContent" in request.url.path
        body = json.loads(request.content.decode())
        prompt_text = body["contents"][0]["parts"][0]["text"]
        assert "Google официально объявил" in prompt_text
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "AI summary text."}]}}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        out = await call_gemini(
            client,
            api_key="gemini_test_key",
            model="gemini-2.0-flash",
            prompt=build_prompt(_item(), max_sentences=3),
        )
    assert out == "AI summary text."


@pytest.mark.asyncio
async def test_enrich_items_replaces_summary(monkeypatch):
    counter = {"n": 0}

    async def fake_call_ai(client, *, settings, prompt):
        counter["n"] += 1
        return f"AI #{counter['n']}"

    monkeypatch.setattr(ai_summarize, "call_ai", fake_call_ai)
    items = [_item(external_id="a/1"), _item(external_id="a/2", title="B")]
    enriched = await enrich_items(items, _settings())
    assert enriched[0].summary == "AI #1"
    assert enriched[1].summary == "AI #2"


@pytest.mark.asyncio
async def test_enrich_items_fallback_on_error(monkeypatch):
    async def failing_call_ai(client, *, settings, prompt):
        raise httpx.HTTPStatusError(
            "rate limit",
            request=httpx.Request(
                "POST",
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
            ),
            response=httpx.Response(429),
        )

    monkeypatch.setattr(ai_summarize, "call_ai", failing_call_ai)
    item = _item()
    enriched = await enrich_items([item], _settings())
    assert enriched[0].summary == item.summary


@pytest.mark.asyncio
async def test_enrich_items_no_key_returns_unchanged():
    item = _item()
    enriched = await enrich_items([item], _settings(ai_api_key=None))
    assert enriched[0] is item


def test_merge_items_into_analysis():
    original = _item(summary="old")
    updated = _item(summary="new")
    analysis = {"categories": {"Cat": [original]}, "stats": {"final_count": 1}}
    merged = merge_items_into_analysis(analysis, [updated])
    assert merged["categories"]["Cat"][0].summary == "new"
