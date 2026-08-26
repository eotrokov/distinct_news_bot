"""Optional Gemini/Groq summaries for digest items (rule-based fallback)."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import replace
from typing import Any
from urllib.parse import quote

import httpx

from bot.config import Settings
from bot.models import NewsItem
from bot.seo_prompt import ITEM_SUMMARY_SYSTEM_PROMPT, build_item_summary_prompt

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_MULTI_SPACE_RE = re.compile(r"\s+")


def ai_summary_active(settings: Settings) -> bool:
    return bool(settings.ai_summary_enabled and settings.ai_api_key)


def item_key(item: NewsItem) -> str:
    return item.external_id or item.url or item.title


def _source_text(item: NewsItem) -> str:
    return (item.body or item.summary or item.title or "").strip()


def _normalize_summary(text: str, *, max_len: int = 700) -> str:
    cleaned = _MULTI_SPACE_RE.sub(" ", (text or "").strip())
    cleaned = cleaned.strip("\"'«»")
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[: max_len - 1].rsplit(" ", 1)[0]
    return (cut or cleaned[: max_len - 1]).rstrip(".,;:") + "…"


def parse_openai_response(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    return _normalize_summary(str(content).strip())


def parse_gemini_response(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    text_parts = [str(part.get("text") or "") for part in parts if part.get("text")]
    return _normalize_summary(" ".join(text_parts).strip())


async def call_groq(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    prompt: str,
) -> str:
    response = await client.post(
        GROQ_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": ITEM_SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 320,
        },
    )
    response.raise_for_status()
    return parse_openai_response(response.json())


async def call_gemini(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    prompt: str,
) -> str:
    url = (
        f"{GEMINI_API_URL}/{quote(model, safe='')}:generateContent"
        f"?key={quote(api_key, safe='')}"
    )
    response = await client.post(
        url,
        headers={"Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": ITEM_SUMMARY_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 320,
            },
        },
    )
    response.raise_for_status()
    return parse_gemini_response(response.json())


async def call_ai(
    client: httpx.AsyncClient,
    *,
    settings: Settings,
    prompt: str,
) -> str:
    api_key = settings.ai_api_key or ""
    if settings.ai_provider == "groq":
        return await call_groq(
            client, api_key=api_key, model=settings.ai_model, prompt=prompt
        )
    return await call_gemini(
        client, api_key=api_key, model=settings.ai_model, prompt=prompt
    )


async def _summarize_one(
    item: NewsItem,
    *,
    settings: Settings,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> NewsItem:
    prompt = build_item_summary_prompt(
        _source_text(item),
        title=item.title or "",
        max_sentences=settings.summary_max_sentences,
    )
    provider = settings.ai_provider
    async with semaphore:
        try:
            summary = await call_ai(client, settings=settings, prompt=prompt)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "%s HTTP error for %s: %s",
                provider,
                item_key(item),
                exc.response.status_code,
            )
            return item
        except httpx.HTTPError as exc:
            logger.warning(
                "%s request failed for %s: %s", provider, item_key(item), exc
            )
            return item
        except Exception:  # noqa: BLE001
            logger.exception("%s summarize failed for %s", provider, item_key(item))
            return item

    if not summary:
        return item
    return replace(item, summary=summary)


async def enrich_items(items: list[NewsItem], settings: Settings) -> list[NewsItem]:
    """Replace summaries with AI output; fallback per item on errors."""
    if not items or not ai_summary_active(settings):
        return items

    semaphore = asyncio.Semaphore(max(1, settings.ai_max_concurrent))
    timeout = httpx.Timeout(settings.ai_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        enriched = await asyncio.gather(
            *[
                _summarize_one(
                    item, settings=settings, client=client, semaphore=semaphore
                )
                for item in items
            ]
        )
    return list(enriched)


def merge_items_into_analysis(
    analysis: dict[str, Any], enriched: list[NewsItem]
) -> dict[str, Any]:
    """Update category buckets with AI-enriched summaries."""
    by_key = {item_key(item): item for item in enriched}
    categories = analysis.get("categories") or {}
    updated: dict[str, list[NewsItem]] = {}
    for name, cat_items in categories.items():
        updated[name] = [by_key.get(item_key(item), item) for item in cat_items]
    return {**analysis, "categories": updated}
