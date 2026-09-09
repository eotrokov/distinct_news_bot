from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

from bot.models import NewsItem

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

# Map RU/EN SEO synonyms (and close transliterations) onto one canonical token so
# the same story in two languages can be merged. Values must already be
# lowercase ASCII / latinized forms without spaces when possible.
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
    "поисковой": "search",
    "поисковая": "search",
    "serp": "serp",
    "выдача": "serp",
    "выдаче": "serp",
    "выдачи": "serp",
    "core": "core",
    "update": "update",
    "апдейт": "update",
    "обновление": "update",
    "обновил": "update",
    "обновила": "update",
    "algorithm": "algorithm",
    "алгоритм": "algorithm",
    "алгоритма": "algorithm",
    "ranking": "ranking",
    "ранжирование": "ranking",
    "ранжирования": "ranking",
    "index": "index",
    "индекс": "index",
    "индексация": "index",
    "индексации": "index",
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

# Tokens too generic to count toward cross-language identity alone.
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


def _token_set(text: str) -> set[str]:
    return {
        t
        for t in normalize_title(text).split()
        if t.isdigit() or len(t) > 2
    }


def _canonical_token(token: str) -> str | None:
    if token.isdigit():
        return token
    mapped = _BILINGUAL_CANON.get(token)
    if mapped:
        return mapped
    # Keep meaningful latin tokens (brands, product names) as anchors.
    if re.fullmatch(r"[a-z0-9][a-z0-9\-_]{2,}", token):
        return token
    return None


def canonical_token_set(text: str) -> set[str]:
    """Language-agnostic token set for RU/EN near-duplicate matching."""
    tokens: set[str] = set()
    for raw in normalize_title(text).split():
        canon = _canonical_token(raw)
        if canon:
            tokens.add(canon)
    return tokens


def _compare_text(item: NewsItem) -> str:
    """Title plus a short excerpt from summary/body for cross-source matching."""
    parts = [item.title or ""]
    extra = (item.summary or item.body or "").strip()
    if extra:
        parts.append(extra[:240])
    return " ".join(parts)


def _cross_lingual_near_duplicate(text_a: str, text_b: str) -> bool:
    """Detect same story told in different languages via shared SEO anchors."""
    ca, cb = canonical_token_set(text_a), canonical_token_set(text_b)
    if not ca or not cb:
        return False
    inter = ca & cb
    if not inter:
        return False

    strong = {t for t in inter if t not in _WEAK_CANON}
    # Same brand/product + same topic word (e.g. ahrefs+update, programmatic+pages).
    if len(strong) >= 2:
        return True
    if len(strong) >= 1 and len(inter) >= 3:
        return True

    # Soft bilingual overlap when both sides share enough mapped tokens.
    union = ca | cb
    jaccard = len(inter) / len(union)
    if jaccard >= 0.45 and len(inter) >= 3:
        return True
    if jaccard >= 0.55 and len(inter) >= 2:
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
        if len(inter) >= 3:
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
