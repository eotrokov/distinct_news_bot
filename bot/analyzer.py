from __future__ import annotations

import logging
import math
import re
import unicodedata
import warnings
from collections import Counter
from dataclasses import replace
from typing import Any

warnings.filterwarnings("ignore", message="Using slow pure-python SequenceMatcher")

from fuzzywuzzy import fuzz

from bot.config import (
    IMPORTANT_KEYWORDS,
    KEYWORD_CATEGORIES,
    STOP_PHRASES,
    STOP_WORDS,
)
from bot.models import NewsItem

logger = logging.getLogger(__name__)

_NOISE_REGEXES = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\butm_[a-z0-9]+=",
        r"\bclid=",
        r"\bref=",
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

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U00002700-\U000027BF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)
_HASHTAG_RE = re.compile(r"#\S+")
_MENTION_RE = re.compile(r"(?<!\w)@\S+")
_SPECIAL_RE = re.compile(r"[^\w\s.,!?;:()\-–—«»\"]+", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")
_SPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"\w+", re.UNICODE)

FUZZY_TITLE_THRESHOLD = 85
TFIDF_THRESHOLD = 0.7
MIN_WORDS = 5

_STOP_SET = {w.lower() for w in STOP_WORDS}


def item_urls(item: NewsItem) -> list[str]:
    urls: list[str] = []
    if item.url:
        urls.append(item.url)
    for u in item.urls or []:
        if u and u not in urls:
            urls.append(u)
    return urls


def _tokenize(text: str) -> list[str]:
    return [
        w
        for w in _WORD_RE.findall((text or "").lower())
        if len(w) > 2 and w not in _STOP_SET
    ]


def _tfidf_cosine(a: str, b: str) -> float:
    """Pairwise TF-IDF cosine without sklearn (VPS-friendly)."""
    # Prefer sklearn when available (larger hosts / optional extra).
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer(stop_words=list(STOP_WORDS))
        matrix = vectorizer.fit_transform([a, b])
        return float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0])
    except Exception:  # noqa: BLE001
        pass

    tok_a, tok_b = _tokenize(a), _tokenize(b)
    if not tok_a or not tok_b:
        return 0.0
    df: Counter[str] = Counter()
    for unique in (set(tok_a), set(tok_b)):
        df.update(unique)
    n_docs = 2

    def vec(tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        total = float(len(tokens)) or 1.0
        out: dict[str, float] = {}
        for term, count in tf.items():
            idf = math.log((n_docs + 1) / (df[term] + 1)) + 1.0
            out[term] = (count / total) * idf
        return out

    va, vb = vec(tok_a), vec(tok_b)
    terms = set(va) | set(vb)
    dot = sum(va.get(t, 0.0) * vb.get(t, 0.0) for t in terms)
    na = math.sqrt(sum(v * v for v in va.values())) or 1.0
    nb = math.sqrt(sum(v * v for v in vb.values())) or 1.0
    return dot / (na * nb)


class NewsAnalyzer:
    """Rule-based news analyzer (no LLM)."""

    def filter_noise(self, items: list[NewsItem]) -> list[NewsItem]:
        kept: list[NewsItem] = []
        for item in items:
            blob = f"{item.title or ''} {item.summary or ''}".lower()
            words = [w for w in re.split(r"\s+", blob) if w]
            if len(words) < MIN_WORDS:
                continue
            if any(phrase in blob for phrase in STOP_PHRASES):
                continue
            if any(rx.search(blob) for rx in _NOISE_REGEXES):
                continue
            kept.append(item)
        return kept

    def deduplicate(self, items: list[NewsItem]) -> list[NewsItem]:
        if not items:
            return []

        unique: list[NewsItem] = []
        for item in items:
            merged_into = False
            for idx, kept in enumerate(unique):
                if self._is_duplicate(item, kept):
                    unique[idx] = self._merge_items(kept, item)
                    merged_into = True
                    break
            if not merged_into:
                unique.append(replace(item, urls=item_urls(item)))
        return unique

    def _is_duplicate(self, a: NewsItem, b: NewsItem) -> bool:
        ta = (a.title or "").strip()
        tb = (b.title or "").strip()
        if ta and tb and fuzz.token_set_ratio(ta, tb) >= FUZZY_TITLE_THRESHOLD:
            return True

        body_a = f"{a.title or ''} {a.summary or ''}".strip()
        body_b = f"{b.title or ''} {b.summary or ''}".strip()
        if len(body_a) < 40 or len(body_b) < 40:
            return False
        try:
            return _tfidf_cosine(body_a, body_b) >= TFIDF_THRESHOLD
        except Exception:  # noqa: BLE001
            return False

    def _merge_items(self, primary: NewsItem, secondary: NewsItem) -> NewsItem:
        urls = item_urls(primary)
        for u in item_urls(secondary):
            if u not in urls:
                urls.append(u)
        summary = primary.summary or secondary.summary
        if len(secondary.summary or "") > len(primary.summary or ""):
            summary = secondary.summary
        published = primary.published_at
        if secondary.published_at and (
            published is None or secondary.published_at < published
        ):
            published = secondary.published_at
        return replace(
            primary,
            urls=urls,
            url=urls[0] if urls else primary.url,
            summary=summary,
            published_at=published,
        )

    def categorize(self, items: list[NewsItem]) -> dict[str, list[NewsItem]]:
        buckets: dict[str, list[NewsItem]] = {name: [] for name in KEYWORD_CATEGORIES}
        other_key = "Прочее важное"
        buckets[other_key] = []

        for item in items:
            blob = f"{item.title or ''} {item.summary or ''}".lower()
            placed = False
            for category, keywords in KEYWORD_CATEGORIES.items():
                if any(kw.lower() in blob for kw in keywords):
                    buckets[category].append(item)
                    placed = True
                    break
            if not placed:
                buckets[other_key].append(item)

        return {k: v for k, v in buckets.items() if v}

    def extract_summary(self, item: NewsItem) -> str:
        text = f"{item.summary or ''}".strip() or (item.title or "")
        text = unicodedata.normalize("NFKC", text)
        text = _HASHTAG_RE.sub(" ", text)
        text = _MENTION_RE.sub(" ", text)
        text = _EMOJI_RE.sub(" ", text)
        text = _SPECIAL_RE.sub(" ", text)
        text = _SPACE_RE.sub(" ", text).strip()
        if not text:
            return ""

        sentences = [
            s.strip()
            for s in _SENTENCE_SPLIT_RE.split(text)
            if len(s.strip()) >= 20
        ]
        if not sentences:
            return text[:200]

        important = {w.lower() for w in IMPORTANT_KEYWORDS}
        for keywords in KEYWORD_CATEGORIES.values():
            important.update(k.lower() for k in keywords)

        best_sentence = sentences[0]
        best_score = float("-inf")
        for sentence in sentences:
            lower = sentence.lower()
            if any(phrase in lower for phrase in STOP_PHRASES):
                continue
            words = _WORD_RE.findall(lower)
            hits = sum(1 for w in words if w in important)
            score = hits - 0.1 * (len(sentence) / 20.0)
            if score > best_score:
                best_score = score
                best_sentence = sentence

        if len(best_sentence) <= 200:
            return best_sentence
        cut = best_sentence[:199].rsplit(" ", 1)[0]
        return (cut or best_sentence[:199]).rstrip(".,;:") + "…"

    def sort_by_importance(self, items: list[NewsItem]) -> list[NewsItem]:
        def score(item: NewsItem) -> int:
            blob = f"{item.title or ''} {item.summary or ''}".lower()
            return sum(1 for kw in IMPORTANT_KEYWORDS if kw.lower() in blob)

        return sorted(items, key=score, reverse=True)

    def process(self, items: list[NewsItem], period: int | None = None) -> dict[str, Any]:
        total = len(items)
        cleaned = self.filter_noise(items)
        filtered_out = total - len(cleaned)

        deduped = self.deduplicate(cleaned)
        deduped_merged = len(cleaned) - len(deduped)

        with_summaries: list[NewsItem] = []
        for item in deduped:
            summary = self.extract_summary(item)
            with_summaries.append(
                replace(item, summary=summary or item.summary, urls=item_urls(item))
            )

        categories = self.categorize(with_summaries)
        sorted_categories = {
            name: self.sort_by_importance(cat_items)
            for name, cat_items in categories.items()
        }
        final_count = sum(len(v) for v in sorted_categories.values())
        stats = {
            "total_processed": total,
            "filtered_out": filtered_out,
            "deduped_merged": deduped_merged,
            "final_count": final_count,
            "period_days": period,
        }
        logger.info(
            "NewsAnalyzer process: total=%s filtered=%s merged=%s final=%s period=%s",
            total,
            filtered_out,
            deduped_merged,
            final_count,
            period,
        )
        return {"categories": sorted_categories, "stats": stats}
