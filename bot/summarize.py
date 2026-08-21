from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_HASHTAG_RE = re.compile(r"#\S+", re.UNICODE)
_MENTION_RE = re.compile(r"(?<!\w)@\S+", re.UNICODE)
_CHANNEL_TAG_RE = re.compile(r"#\S*@\S+", re.UNICODE)
_URL_RE = re.compile(r"https?://\S+|t\.me/\S+", re.IGNORECASE)
_HTML_RE = re.compile(r"<[^>]+>")
_BRACKETS_RE = re.compile(r"\([^)]{0,120}\)|（[^）]{0,120}）|«[^»]{0,40}»")
_MULTI_SPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")

# Intro fluff typical for TG channels / blogs.
_SKIP_PREFIXES = (
    "сегодня мы",
    "сегодня я",
    "сегодня разбер",
    "сегодня поговорим",
    "сегодня обсуд",
    "напоминаю",
    "напомню",
    "по заявкам",
    "тот самый материал",
    "как и обещал",
    "как обещал",
    "друзья,",
    "привет,",
    "всем привет",
    "добрый день",
    "доброе утро",
    "добрый вечер",
    "в этом посте",
    "в сегодняшнем",
    "подписывайтесь",
    "ставьте лайк",
    "переходите по ссылке",
    "читайте также",
    "продолжение ниже",
    "spoiler",
    "важно:",
    "внимание:",
)

# Prefer sentences that look like news facts.
_NEWS_HINTS = (
    "объявил",
    "объявила",
    "объявили",
    "запустил",
    "запустила",
    "запустили",
    "опубликовал",
    "опубликовала",
    "опубликовали",
    "заявил",
    "заявила",
    "заявили",
    "сообщил",
    "сообщила",
    "сообщили",
    "изменил",
    "изменила",
    "изменили",
    "представил",
    "представила",
    "представили",
    "утвердил",
    "утвердила",
    "принял",
    "приняла",
    "подписал",
    "подписала",
    "купил",
    "продали",
    "выпустил",
    "выпустила",
    "заблокировал",
    "запретил",
    "разрешил",
    "увеличил",
    "снизил",
    "вырос",
    "упал",
    "стал",
    "стала",
    "будут",
    "будет",
    "announced",
    "launched",
    "released",
    "said",
    "reported",
)


def strip_html(text: str) -> str:
    cleaned = _HTML_RE.sub(" ", text or "")
    return _MULTI_SPACE_RE.sub(" ", cleaned).strip()


def clean_text(text: str) -> str:
    """Remove hashtags, mentions, URLs and light noise."""
    text = strip_html(text)
    text = _CHANNEL_TAG_RE.sub(" ", text)
    text = _HASHTAG_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    # Drop very short parenthetical asides, keep longer ones that may carry facts.
    text = re.sub(r"\([^)]{0,60}\)", " ", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip(" \t\r\n-–—|•")
    return text


def _is_intro(sentence: str) -> bool:
    lower = sentence.lower().lstrip("«\"'„ ")
    return any(lower.startswith(prefix) or f" {prefix}" in lower[:40] for prefix in _SKIP_PREFIXES)


def _has_news_hint(sentence: str) -> bool:
    lower = sentence.lower()
    return any(hint in lower for hint in _NEWS_HINTS)


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT_RE.split(text)
    out: list[str] = []
    for part in parts:
        s = part.strip(" \t\r\n-–—|•")
        if len(s) >= 20:
            out.append(s)
    return out


def _clip(text: str, limit: int) -> str:
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return (cut or text[: limit - 1]).rstrip(".,;:") + "…"


def _sumy_summary(text: str, max_sentences: int = 1) -> str | None:
    """Optional LSA summary via sumy; returns None if unavailable."""
    try:
        from sumy.nlp.tokenizers import Tokenizer
        from sumy.parsers.plaintext import PlaintextParser
        from sumy.summarizers.lsa import LsaSummarizer
    except Exception:  # noqa: BLE001
        return None

    try:
        # Russian tokenizer if available, else english as a soft fallback.
        try:
            tokenizer = Tokenizer("russian")
        except Exception:  # noqa: BLE001
            tokenizer = Tokenizer("english")
        parser = PlaintextParser.from_string(text, tokenizer)
        summarizer = LsaSummarizer()
        sentences = list(summarizer(parser.document, max_sentences))
        if not sentences:
            return None
        joined = " ".join(str(s) for s in sentences).strip()
        return joined or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("sumy summarization skipped: %s", exc)
        return None


def clean_and_summarize(
    text: str,
    *,
    max_len: int = 220,
    max_sentences: int = 1,
    title: str | None = None,
) -> str:
    """Build a short factual summary without intro fluff and hashtags."""
    cleaned = clean_text(text or "")
    if not cleaned:
        return ""

    # Short posts: just cleaned text.
    if len(cleaned) < 80:
        return _clip(cleaned, max_len)

    sentences = _split_sentences(cleaned)
    if not sentences:
        return _clip(cleaned, max_len)

    # Prefer non-intro sentences with news-like verbs.
    ranked: list[str] = []
    for sentence in sentences:
        if _is_intro(sentence):
            continue
        if title and sentence.lower().startswith(title.lower()[:40]):
            # Title restatement is ok but deprioritize exact duplicates later.
            pass
        ranked.append(sentence)

    if not ranked:
        ranked = [s for s in sentences if not _is_intro(s)] or sentences

    hinted = [s for s in ranked if _has_news_hint(s)]
    candidates = hinted or ranked

    chosen = candidates[0]
    # For longer articles try sumy, then re-clean.
    if len(cleaned) > 400 and max_sentences >= 1:
        sumy_text = _sumy_summary(cleaned, max_sentences=max_sentences)
        if sumy_text:
            sumy_clean = clean_text(sumy_text)
            if sumy_clean and not _is_intro(sumy_clean):
                chosen = sumy_clean

    # If first candidate is still weak and we have a better hinted one later.
    if not _has_news_hint(chosen):
        for sentence in candidates[1:]:
            if len(sentence) > 30 and _has_news_hint(sentence):
                chosen = sentence
                break

    return _clip(chosen, max_len)


def first_meaningful_line(text: str, *, max_len: int = 240) -> str:
    """Pick a non-intro first line for Telegram-style titles."""
    cleaned = clean_text(text or "")
    if not cleaned:
        return ""
    for line in re.split(r"[\n\r]+", cleaned):
        line = line.strip(" -–—|•")
        if len(line) < 12:
            continue
        if _is_intro(line):
            continue
        return _clip(line, max_len)
    return _clip(cleaned, max_len)
