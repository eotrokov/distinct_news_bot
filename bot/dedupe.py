from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

from bot.models import NewsItem

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

# Map RU/EN SEO synonyms (and close transliterations) onto one canonical token so
# the same story can be compared as translated text. Values must already be
# lowercase ASCII / latinized forms without spaces when possible.
# This lexicon is for translation of wording — not a list of "tags" that alone
# mark two posts as duplicates.
_BILINGUAL_CANON: dict[str, str] = {
    # programmatic SEO / pages
    "programmatic": "programmatic",
    "программатик": "programmatic",
    "программный": "programmatic",
    "pages": "pages",
    "page": "pages",
    "страницы": "pages",
    "страниц": "pages",
    "страница": "pages",
    "страницу": "pages",
    "landing": "landing",
    "лендинг": "landing",
    "лендинги": "landing",
    # search / google
    "google": "google",
    "гугл": "google",
    "гугла": "google",
    "гугле": "google",
    "search": "search",
    "поиска": "search",
    "поиск": "search",
    "поиске": "search",
    "поиском": "search",
    "поисковой": "search",
    "поисковая": "search",
    "поисковых": "search",
    "serp": "serp",
    "выдача": "serp",
    "выдаче": "serp",
    "выдачи": "serp",
    "выдачу": "serp",
    "core": "core",
    "update": "update",
    "апдейт": "update",
    "обновление": "update",
    "обновления": "update",
    "обновил": "update",
    "обновила": "update",
    "обновили": "update",
    "algorithm": "algorithm",
    "алгоритм": "algorithm",
    "алгоритма": "algorithm",
    "алгоритмов": "algorithm",
    "ranking": "ranking",
    "ранжирование": "ranking",
    "ранжирования": "ranking",
    "ранжировании": "ranking",
    "index": "index",
    "индекс": "index",
    "индекса": "index",
    "индексация": "index",
    "индексации": "index",
    "индексацию": "index",
    "crawl": "crawl",
    "crawling": "crawl",
    "краулинг": "crawl",
    "краулер": "crawl",
    "yandex": "yandex",
    "яндекс": "yandex",
    "webmaster": "webmaster",
    "вебмастер": "webmaster",
    "snippet": "snippet",
    "сниппет": "snippet",
    "сниппета": "snippet",
    # link building
    "linkbuilding": "linkbuilding",
    "linkbuild": "linkbuilding",
    "линкбилдинг": "linkbuilding",
    "линкбилд": "linkbuilding",
    "backlink": "backlink",
    "backlinks": "backlink",
    "бэклинк": "backlink",
    "бэклинки": "backlink",
    "ссылки": "links",
    "ссылка": "links",
    "ссылок": "links",
    "ссылку": "links",
    "links": "links",
    "link": "links",
    # tools
    "ahrefs": "ahrefs",
    "semrush": "semrush",
    "serpstat": "serpstat",
    "majestic": "majestic",
    "screaming": "screamingfrog",
    "frog": "screamingfrog",
    # content / seo
    "seo": "seo",
    "сео": "seo",
    "content": "content",
    "контент": "content",
    "контента": "content",
    "copywriting": "copywriting",
    "копирайтинг": "copywriting",
    "копирайт": "copywriting",
    "keyword": "keyword",
    "keywords": "keyword",
    "ключевые": "keyword",
    "ключ": "keyword",
    "ключей": "keyword",
    "semantic": "semantic",
    "семантика": "semantic",
    "семантик": "semantic",
    "семантическое": "semantic",
    # ai
    "chatgpt": "chatgpt",
    "gemini": "gemini",
    "claude": "claude",
    "нейросеть": "ai",
    "нейросети": "ai",
    "нейросетей": "ai",
    "overview": "overview",
    "overviews": "overview",
    # analytics
    "analytics": "analytics",
    "аналитика": "analytics",
    "аналитики": "analytics",
    "traffic": "traffic",
    "трафик": "traffic",
    "трафика": "traffic",
    "conversion": "conversion",
    "конверсия": "conversion",
    "конверсии": "conversion",
    # common verbs / event words in headlines
    "launch": "launch",
    "launches": "launch",
    "launched": "launch",
    "запуск": "launch",
    "запустила": "launch",
    "запустил": "launch",
    "запускает": "launch",
    "release": "release",
    "releases": "release",
    "released": "release",
    "релиз": "release",
    "выпустил": "release",
    "выпустила": "release",
    "выпускает": "release",
    "scale": "scale",
    "scaling": "scale",
    "масштабировать": "scale",
    "масштабирование": "scale",
    "масштабирования": "scale",
    "guide": "guide",
    "гайд": "guide",
    "how": "howto",
    "как": "howto",
}

# Generic topic tags — overlap on these alone must never mark a duplicate.
# Cross-lingual matches need shared distinctive story anchors + text-like overlap.
_WEAK_CANON = frozenset(
    {
        "howto",
        "guide",
        "update",
        "release",
        "launch",
        "pages",
        "links",
        "content",
        "search",
        "seo",
        "serp",
        "index",
        "algorithm",
        "ranking",
        "analytics",
        "traffic",
        "conversion",
        "crawl",
        "keyword",
        "semantic",
        "ai",
        "overview",
        "snippet",
        "webmaster",
    }
)


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title or "").lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def fingerprint_for(item: NewsItem) -> str:
    """Stable fingerprint used for exact/near-duplicate tracking."""
    normalized = normalize_title(item.title)
    if normalized:
        payload = f"title:{normalized}"
    elif item.url:
        payload = f"url:{item.url.strip().lower()}"
    else:
        payload = f"raw:{item.title}|{item.url}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Glue / boilerplate tokens ignored when scoring text similarity.
_COMPARE_STOP = frozenset(
    {
        "как",
        "для",
        "или",
        "при",
        "без",
        "что",
        "это",
        "все",
        "всё",
        "под",
        "над",
        "про",
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "are",
        "was",
        "how",
        "its",
        "into",
        "over",
        "after",
        "about",
        "new",
        "you",
        "your",
        "our",
        "seo",
        "сео",
    }
)


def _token_set(text: str) -> set[str]:
    return {
        t
        for t in normalize_title(text).split()
        if t.isdigit() or len(t) > 2
    }


def _meaningful_tokens(tokens: set[str]) -> set[str]:
    """Drop short glue words so boilerplate cannot force a merge."""
    return {
        t
        for t in tokens
        if t not in _COMPARE_STOP and (t.isdigit() or len(t) > 3)
    }


def _canonical_token(token: str) -> str | None:
    """Map a raw token via the bilingual lexicon (digits stay as-is)."""
    if token.isdigit():
        return token
    return _BILINGUAL_CANON.get(token)


def canonical_token_set(text: str) -> set[str]:
    """Translated story tokens for RU/EN near-duplicate matching.

    Only lexicon-mapped words and digits are kept. Arbitrary latin filler
    (confirms, practical, …) is dropped so English prose does not dilute
    Jaccard against a translated Russian headline.
    """
    tokens: set[str] = set()
    for raw in normalize_title(text).split():
        canon = _canonical_token(raw)
        if canon:
            tokens.add(canon)
    return tokens


def _translated_token_sequence(text: str) -> list[str]:
    """Order-preserving bilingual translation of lexicon tokens (+ digits)."""
    out: list[str] = []
    for raw in normalize_title(text).split():
        canon = _canonical_token(raw)
        if canon:
            out.append(canon)
    return out


def _compare_text(item: NewsItem) -> str:
    """Title plus a short excerpt from summary/body for cross-source matching."""
    parts = [item.title or ""]
    extra = (item.summary or item.body or "").strip()
    if extra:
        parts.append(extra[:240])
    return " ".join(parts)


def _cross_lingual_near_duplicate(text_a: str, text_b: str) -> bool:
    """Same story in different languages: compare translated text, not topic tags.

    We rewrite known RU↔EN synonyms, then require:
    - at least two distinctive (non-tag) shared anchors, and
    - high Jaccard / sequence similarity on the translated token sets.
    Sharing only category tags (seo, google+serp, …) is not enough.
    """
    seq_a = _translated_token_sequence(text_a)
    seq_b = _translated_token_sequence(text_b)
    ca, cb = set(seq_a), set(seq_b)
    if len(ca) < 3 or len(cb) < 3:
        return False

    inter = ca & cb
    if not inter:
        return False

    strong = {t for t in inter if t not in _WEAK_CANON}
    # Topic-tag overlap alone (seo+guide, google+serp, …) must not merge stories.
    if len(strong) < 2:
        return False

    union = ca | cb
    jaccard = len(inter) / len(union)
    ratio = SequenceMatcher(
        None, " ".join(seq_a), " ".join(seq_b)
    ).ratio()
    containment = len(inter) / min(len(ca), len(cb))

    # Text-like similarity after translation.
    if ratio >= 0.72 and jaccard >= 0.5:
        return True
    if jaccard >= 0.6 and containment >= 0.7:
        return True
    if len(strong) >= 3 and jaccard >= 0.5:
        return True
    return False


def are_near_duplicates(a: NewsItem, b: NewsItem, threshold: float = 0.86) -> bool:
    if a.url and b.url and a.url.rstrip("/") == b.url.rstrip("/"):
        return True

    text_a = _compare_text(a)
    text_b = _compare_text(b)
    ta = normalize_title(text_a)
    tb = normalize_title(text_b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True

    ratio = SequenceMatcher(None, ta, tb).ratio()
    if ratio >= threshold:
        return True

    sa, sb = _token_set(text_a), _token_set(text_b)
    if sa and sb:
        jaccard = len(sa & sb) / len(sa | sb)
        if jaccard >= 0.75 and ratio >= 0.72:
            return True

        inter = sa & sb
        meaningful = _meaningful_tokens(inter)
        # Require shared content words (not «как/для/seo/гайд» boilerplate).
        if len(meaningful) >= 3:
            containment = len(inter) / min(len(sa), len(sb))
            if containment >= 0.5 and ratio >= 0.4:
                return True

    if _cross_lingual_near_duplicate(text_a, text_b):
        return True

    return False


def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    """Drop duplicates across sources, keeping the earliest published item."""

    def sort_key(item: NewsItem) -> tuple:
        published = item.published_at.timestamp() if item.published_at else float("inf")
        return (published, item.title)

    ordered = sorted(items, key=sort_key)
    unique: list[NewsItem] = []
    seen_fp: set[str] = set()

    for item in ordered:
        fp = fingerprint_for(item)
        if fp in seen_fp:
            continue
        if any(are_near_duplicates(item, kept) for kept in unique):
            continue
        seen_fp.add(fp)
        unique.append(item)

    return unique
