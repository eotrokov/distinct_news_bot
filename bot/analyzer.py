from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from bot.dedupe import are_near_duplicates
from bot.models import NewsItem
from bot.summarize import clean_and_summarize

logger = logging.getLogger(__name__)

MIN_WORDS = 5

_NOISE_REGEXES = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\butm_[a-z0-9]+=",
        r"\bclid=",
        r"купить",
        r"скидк",
        r"акци[яи]",
        r"промокод",
        r"бесплатн\w*\s+подписк",
        r"реклама",
        r"erid=",
        r"партн[её]рск",
        r"заказать\s+сейчас",
        r"только\s+сегодня",
        r"успей\s+купить",
        r"\bsubscribe\b",
        r"\bdiscount\b",
        r"\bcoupon\b",
        r"\bbuy\s+now\b",
    )
]

STOP_PHRASES = [
    "всем привет",
    "доброе утро",
    "добрый день",
    "добрый вечер",
    "не забудьте подписаться",
    "подписывайтесь",
    "подпишись на канал",
    "подпишитесь",
    "ставьте лайк",
    "жми лайк",
    "пишите в комментах",
    "пишите в комментариях",
    "ссылка в описании",
    "ссылка в шапке",
    "ссылка в био",
    "переходи по ссылке",
    "переходите по ссылке",
    "реклама",
    "промокод",
    "успей купить",
    "только сегодня",
    "бесплатная подписка",
    "партнерский материал",
    "партнёрский материал",
    "наш курс",
    "запись на курс",
    "buy now",
    "limited offer",
    "subscribe now",
    "follow us",
]

BLOCK_WORDS = [
    "розыгрыш",
    "giveaway",
    "конкурс",
    "промокод",
    "марафон",
    "вебинар",
    "подписывайтесь",
    "подпишись",
    "лайкните",
    "репост",
    "реклама",
    "erid",
    "coupon",
]

_STOP_PHRASES = [p.lower() for p in STOP_PHRASES]
_BLOCK_WORDS = [w.lower() for w in BLOCK_WORDS]


def item_urls(item: NewsItem) -> list[str]:
    urls: list[str] = []
    if item.url:
        urls.append(item.url)
    for url in item.urls or []:
        if url and url not in urls:
            urls.append(url)
    return urls


class NewsAnalyzer:
    """Same pipeline as weekly digests: drop noise, merge dupes, rank by reactions."""

    def filter_noise(self, items: list[NewsItem]) -> list[NewsItem]:
        kept: list[NewsItem] = []
        for item in items:
            blob = f"{item.title or ''} {item.summary or item.body or ''}".lower()
            words = [w for w in re.split(r"\s+", blob) if w]
            if len(words) < MIN_WORDS:
                continue
            if any(phrase in blob for phrase in _STOP_PHRASES):
                continue
            if any(word in blob for word in _BLOCK_WORDS):
                continue
            if any(rx.search(blob) for rx in _NOISE_REGEXES):
                continue
            kept.append(item)
        return kept

    def deduplicate(self, items: list[NewsItem]) -> list[NewsItem]:
        unique: list[NewsItem] = []
        for item in items:
            merged = False
            for idx, kept in enumerate(unique):
                if are_near_duplicates(item, kept):
                    unique[idx] = self._merge_items(kept, item)
                    merged = True
                    break
            if not merged:
                unique.append(replace(item, urls=item_urls(item)))
        return unique

    def _merge_items(self, primary: NewsItem, secondary: NewsItem) -> NewsItem:
        urls = item_urls(primary)
        for url in item_urls(secondary):
            if url not in urls:
                urls.append(url)
        summary = primary.summary or secondary.summary
        if len(secondary.summary or "") > len(primary.summary or ""):
            summary = secondary.summary
        published = primary.published_at
        if secondary.published_at and (
            published is None or secondary.published_at < published
        ):
            published = secondary.published_at
        reactions = max(int(primary.reactions or 0), int(secondary.reactions or 0))
        views = max(int(primary.views or 0), int(secondary.views or 0))
        title = primary.title
        if len(secondary.title or "") > len(primary.title or ""):
            title = secondary.title
        return replace(
            primary,
            title=title,
            urls=urls,
            url=urls[0] if urls else primary.url,
            summary=summary,
            published_at=published,
            reactions=reactions,
            views=views,
        )

    def sort_by_reactions(self, items: list[NewsItem]) -> list[NewsItem]:
        def score(item: NewsItem) -> tuple[int, int, float]:
            published = (
                item.published_at.timestamp()
                if item.published_at
                else datetime.min.replace(tzinfo=timezone.utc).timestamp()
            )
            return (int(item.reactions or 0), int(item.views or 0), published)

        return sorted(items, key=score, reverse=True)

    def process(
        self,
        items: list[NewsItem],
        period: int | None = None,
        *,
        max_sentences: int = 3,
    ) -> dict[str, Any]:
        total = len(items)
        cleaned = self.filter_noise(items)
        filtered_out = total - len(cleaned)
        deduped = self.deduplicate(cleaned)
        deduped_merged = len(cleaned) - len(deduped)

        with_summaries: list[NewsItem] = []
        for item in deduped:
            source_text = item.body or item.summary or item.title
            summary = clean_and_summarize(
                source_text,
                title=item.title,
                max_sentences=max_sentences,
            )
            with_summaries.append(
                replace(
                    item,
                    summary=summary or item.summary or item.title,
                    urls=item_urls(item),
                )
            )

        ranked = self.sort_by_reactions(with_summaries)
        category = "🔥 Главное за неделю" if period == 7 else "🔥 Главное"
        stats = {
            "total_processed": total,
            "filtered_out": filtered_out,
            "deduped_merged": deduped_merged,
            "final_count": len(ranked),
            "period_days": period,
            "sort_by": "reactions",
        }
        logger.info(
            "NewsAnalyzer process: total=%s filtered=%s merged=%s final=%s period=%s",
            total,
            filtered_out,
            deduped_merged,
            len(ranked),
            period,
        )
        return {"categories": {category: ranked} if ranked else {}, "stats": stats}
