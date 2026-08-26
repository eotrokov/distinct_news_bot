from __future__ import annotations

from bot.ai_summarize import (
    merge_items_into_analysis,
    parse_gemini_response,
    parse_openai_response,
)
from bot.models import NewsItem
from bot.seo_prompt import (
    SEO_DIGEST_SYSTEM_PROMPT,
    SEO_CATEGORIES,
    build_item_summary_prompt,
)


def test_system_prompt_mentions_required_blocks():
    assert "Google и Поиск" in SEO_DIGEST_SYSTEM_PROMPT
    assert "Линкбилдинг и E-E-A-T" in SEO_DIGEST_SYSTEM_PROMPT
    assert "строго 2 предложения" in SEO_DIGEST_SYSTEM_PROMPT
    assert len(SEO_CATEGORIES) == 6


def test_build_item_summary_prompt_asks_for_two_sentences():
    prompt = build_item_summary_prompt(
        "Google подтвердил core update",
        title="Core update",
        max_sentences=2,
    )
    assert "2 информативных" in prompt
    assert "Core update" in prompt


def test_parse_openai_and_gemini_responses():
    openai_payload = {
        "choices": [
            {
                "message": {
                    "content": "  Факт один. Деталь два.  ",
                }
            }
        ]
    }
    assert parse_openai_response(openai_payload) == "Факт один. Деталь два."

    gemini_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Первое."},
                        {"text": " Второе."},
                    ]
                }
            }
        ]
    }
    assert parse_gemini_response(gemini_payload) == "Первое. Второе."


def test_merge_items_into_analysis():
    original = NewsItem(
        title="A",
        url="https://a.example/1",
        published_at=None,
        source_type="telegram",
        source_name="t",
        summary="old",
        external_id="id-1",
    )
    enriched = NewsItem(
        title="A",
        url="https://a.example/1",
        published_at=None,
        source_type="telegram",
        source_name="t",
        summary="new ai summary",
        external_id="id-1",
    )
    analysis = {
        "categories": {"🔍 Google и Поиск": [original]},
        "stats": {"final_count": 1},
    }
    merged = merge_items_into_analysis(analysis, [enriched])
    assert merged["categories"]["🔍 Google и Поиск"][0].summary == "new ai summary"
