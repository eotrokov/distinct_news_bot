from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import replace
from typing import Any

import httpx

from bot.config import Settings
from bot.models import NewsItem

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_MULTI_SPACE_RE = re.compile(r"\s+")


def ai_summary_active(settings: Settings) -> bool:
    return bool(settings.ai_summary_enabled and settings.groq_api_key)


def item_key(item: NewsItem) -> str:
    return item.external_id or item.url or item.title


def _item_key(item: NewsItem) -> str:
    return item_key(item)


def _source_text(item: NewsItem) -> str:
    parts: list[str] = []
    title = (item.title or "").strip()
    body = (item.body or item.summary or "").strip()
    if title:
        parts.append(f"Заголовок: {title}")
    if body:
        parts.append(f"Текст поста:\n{body}")
    return "\n\n".join(parts)


def build_prompt(item: NewsItem, *, max_sentences: int) -> str:
    keep = max(2, int(max_sentences))
    return (
        "Ты редактор SEO-дайджеста. Сожми пост в "
        f"{keep} информативных предложения на русском языке.\n"
        "Правила:\n"
        "- только факты из текста, без выдумок;\n"
        "- без приветствий, рекламы, призывов подписаться;\n"
        "- без хештегов, упоминаний и ссылок;\n"
        "- ответ — только сводка, без пояснений.\n\n"
        f"{_source_text(item)}"
    )


def _normalize_summary(text: str, *, max_len: int = 700) -> str:
    cleaned = _MULTI_SPACE_RE.sub(" ", (text or "").strip())
    cleaned = cleaned.strip("\"'«»")
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[: max_len - 1].rsplit(" ", 1)[0]
    return (cut or cleaned[: max_len - 1]).rstrip(".,;:") + "…"


def parse_groq_response(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    return _normalize_summary(str(content).strip())


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
                {
                    "role": "system",
                    "content": (
                        "Ты лаконичный редактор новостей SEO-тематики. "
                        "Пиши только на русском."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 320,
        },
    )
    response.raise_for_status()
    return parse_groq_response(response.json())


async def _summarize_one(
    item: NewsItem,
    *,
    settings: Settings,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> NewsItem:
    prompt = build_prompt(item, max_sentences=settings.summary_max_sentences)
    async with semaphore:
        try:
            summary = await call_groq(
                client,
                api_key=settings.groq_api_key or "",
                model=settings.ai_model,
                prompt=prompt,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Groq HTTP error for %s: %s",
                _item_key(item),
                exc.response.status_code,
            )
            return item
        except httpx.HTTPError as exc:
            logger.warning("Groq request failed for %s: %s", _item_key(item), exc)
            return item
        except Exception:  # noqa: BLE001
            logger.exception("Groq summarize failed for %s", _item_key(item))
            return item

    if not summary:
        return item
    return replace(item, summary=summary)


async def enrich_items(items: list[NewsItem], settings: Settings) -> list[NewsItem]:
    """Replace summaries with Groq AI output; fallback per item on errors."""
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
    by_key = {_item_key(item): item for item in enriched}
    categories = analysis.get("categories") or {}
    updated: dict[str, list[NewsItem]] = {}
    for name, cat_items in categories.items():
        updated[name] = [
            by_key.get(_item_key(item), item) for item in cat_items
        ]
    return {**analysis, "categories": updated}
