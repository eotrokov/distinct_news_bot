from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from bot.dedupe import are_near_duplicates
from bot.models import NewsItem
from bot.seo_prompt import SEO_CATEGORIES, SEO_RELEVANCE_KEYWORDS
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
        # SEO-specific promo / hiring / courses
        r"куп(ить|лю|им)\s+ссылк",
        r"прода(м|жа|ём|ем)\s+ссылк",
        r"нативн\w*\s+интеграц",
        r"ищу\s+(seo|сео|специалист|менеджер|линкбилдер)",
        r"ваканси",
        r"требуется\s+(seo|сео|специалист)",
        r"запись\s+на\s+курс",
        r"прода(жа|ём|ем)\s+курс",
        r"наш\s+курс",
        r"интенсив\s+для",
        r"стоимость\s+размещен",
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
    "ищу специалиста",
    "ищу seo",
    "ищу сео",
    "купить ссылки",
    "продажа ссылок",
    "нативная интеграция",
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
    "вакансия",
    "инфобиз",
]

_STOP_PHRASES = [p.lower() for p in STOP_PHRASES]
_BLOCK_WORDS = [w.lower() for w in BLOCK_WORDS]
_RELEVANCE = [kw.lower() for kw in SEO_RELEVANCE_KEYWORDS]


def item_urls(item: NewsItem) -> list[str]:
    urls: list[str] = []
    if item.url:
        urls.append(item.url)
    for url in item.urls or []:
        if url and url not in urls:
            urls.append(url)
    return urls


def _blob(item: NewsItem) -> str:
    return f"{item.title or ''} {item.summary or item.body or ''}".lower()


def is_seo_relevant(item: NewsItem) -> bool:
    blob = _blob(item)
    return any(kw in blob for kw in _RELEVANCE)


def categorize_item(item: NewsItem) -> str | None:
    """Return the best-matching SEO category, or None if none match."""
    blob = _blob(item)
    best_name: str | None = None
    best_score = 0
    for category, keywords in SEO_CATEGORIES.items():
        hits = [kw for kw in keywords if kw.lower() in blob]
        if not hits:
            continue
        # Prefer more / longer keyword hits so "ahrefs"+"dr" beats bare "dr ".
        score = sum(len(kw) for kw in hits) + len(hits) * 2
        if score > best_score:
            best_score = score
            best_name = category
    return best_name


class NewsAnalyzer:
    """SEO digest pipeline: noise filter, relevance, dedupe, categorize, rank."""

    def filter_noise(self, items: list[NewsItem]) -> list[NewsItem]:
        kept: list[NewsItem] = []
        for item in items:
            blob = _blob(item)
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

    def filter_relevant(self, items: list[NewsItem]) -> list[NewsItem]:
        return [item for item in items if is_seo_relevant(item)]

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
        # Prefer the variant with more reactions (then views), per SEO digest rules.
        if (int(secondary.reactions or 0), int(secondary.views or 0)) > (
            int(primary.reactions or 0),
            int(primary.views or 0),
        ):
            primary, secondary = secondary, primary

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

    def categorize(self, items: list[NewsItem]) -> dict[str, list[NewsItem]]:
        buckets: dict[str, list[NewsItem]] = {name: [] for name in SEO_CATEGORIES}
        for item in items:
            category = categorize_item(item)
            if category is None:
                # Relevant but no specific block — put under Google/Search as default
                # only if it still looks search-related; else skip orphan.
                continue
            buckets[category].append(item)
        # Drop empty blocks; keep declared order.
        return {
            name: self.sort_by_reactions(cat_items)
            for name, cat_items in buckets.items()
            if cat_items
        }

    def process(
        self,
        items: list[NewsItem],
        period: int | None = None,
        *,
        max_sentences: int = 2,
    ) -> dict[str, Any]:
        total = len(items)
        cleaned = self.filter_noise(items)
        relevant = self.filter_relevant(cleaned)
        filtered_out = total - len(relevant)
        deduped = self.deduplicate(relevant)
        deduped_merged = len(relevant) - len(deduped)

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

        categories = self.categorize(with_summaries)
        final_count = sum(len(v) for v in categories.values())
        stats = {
            "total_processed": total,
            "filtered_out": filtered_out,
            "deduped_merged": deduped_merged,
            "final_count": final_count,
            "period_days": period,
            "sort_by": "reactions",
        }
        logger.info(
            "NewsAnalyzer process: total=%s filtered=%s merged=%s final=%s period=%s",
            total,
            filtered_out,
            deduped_merged,
            final_count,
            period,
        )
        return {"categories": categories, "stats": stats}
