from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_HASHTAG_RE = re.compile(r"#\S+", re.UNICODE)
_MENTION_RE = re.compile(r"(?<!\w)@\S+", re.UNICODE)
_CHANNEL_TAG_RE = re.compile(r"#\S*@\S+", re.UNICODE)
_URL_RE = re.compile(r"https?://\S+|t\.me/\S+", re.IGNORECASE)
_HTML_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")
_LEADING_PAREN_RE = re.compile(r"^\([^)]{3,160}\)\s*")

# Whole-sentence intros / meta talk to skip.
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
    "мы много писали",
    "мы уже писали",
    "я много писал",
    "я уже писал",
    "как мы писали",
    "как я писал",
    "например тут",
    "полностью",
)

# Definition / fluff middles to skip.
_SKIP_CONTAINS = (
    "— это ",
    " - это ",
    "это специальн",
    "это особое",
    "которым можно делиться",
    "прикольный заход",
)

_NEWS_HINTS = (
    "объявил",
    "объявила",
    "объявили",
    "запустил",
    "запустила",
    "запустили",
    "запускает",
    "опубликован",
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
    "рассматривает",
    "позволяет",
    "оптимизир",
    "утвердил",
    "принял",
    "подписал",
    "выпустил",
    "выпустила",
    "заблокировал",
    "запретил",
    "разрешил",
    "увеличил",
    "снизил",
    "вырос",
    "упал",
    "алгоритм",
    "продвижен",
    "нейросет",
    "профил",
    "announced",
    "launched",
    "launches",
    "released",
    "reported",
)

# "Сегодня мы разберем X" → factual rewrite of X.
_REWRITE_LEAD_INS = [
    (
        re.compile(
            r"^(?:сегодня\s+)?(?:мы|я)\s+разбер[её]м\s+(.+)$",
            re.IGNORECASE | re.DOTALL,
        ),
        "Опубликован {payload}",
    ),
    (
        re.compile(
            r"^(?:сегодня\s+)?(?:мы|я)\s+поговорим\s+(?:о|об)\s+(.+)$",
            re.IGNORECASE | re.DOTALL,
        ),
        "{payload}",
    ),
    (
        re.compile(
            r"^(?:сегодня\s+)?(?:мы|я)\s+обсуд\w+\s+(.+)$",
            re.IGNORECASE | re.DOTALL,
        ),
        "{payload}",
    ),
    (
        re.compile(
            r"^(?:текущая|новая)\s+работа\s+делает\s+.+?[—–-]\s*(рассматривает\s+.+)$",
            re.IGNORECASE | re.DOTALL,
        ),
        "Новая работа {payload}",
    ),
    (
        re.compile(
            r"^(?:текущая|новая)\s+работа\s+рассматривает\s+(.+)$",
            re.IGNORECASE | re.DOTALL,
        ),
        "Новая работа рассматривает {payload}",
    ),
]

_COMPRESS_PHRASES = [
    (
        re.compile(
            r",?\s*включающ\w+\s+в\s+себя\s+исключительно\s+те\s+шаги,\s*"
            r"которые\s+дают\s+наибольшую\s+эффективность\.?",
            re.IGNORECASE,
        ),
        " с акцентом на самые эффективные шаги",
    ),
    (
        re.compile(r"\s+полностью\.?$", re.IGNORECASE),
        "",
    ),
]


def strip_html(text: str) -> str:
    cleaned = _HTML_RE.sub(" ", text or "")
    return _MULTI_SPACE_RE.sub(" ", cleaned).strip()


def clean_text(text: str) -> str:
    """Remove hashtags, mentions, URLs and light noise."""
    text = strip_html(text)
    text = _LEADING_PAREN_RE.sub("", text)
    text = _CHANNEL_TAG_RE.sub(" ", text)
    text = _HASHTAG_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    # Drop short parenthetical asides ("например тут и тут").
    text = re.sub(r"\([^)]{0,80}\)", " ", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip(" \t\r\n-–—|•")
    return text


def _is_intro(sentence: str) -> bool:
    lower = sentence.lower().lstrip("«\"'„ ")
    if any(lower.startswith(prefix) for prefix in _SKIP_PREFIXES):
        return True
    if any(token in lower for token in _SKIP_CONTAINS):
        return True
    return False


def _has_news_hint(sentence: str) -> bool:
    lower = sentence.lower()
    return any(hint in lower for hint in _NEWS_HINTS)


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT_RE.split(text)
    out: list[str] = []
    for part in parts:
        s = part.strip(" \t\r\n-–—|•")
        if len(s) >= 18:
            out.append(s)
    return out


def _clip(text: str, limit: int) -> str:
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return (cut or text[: limit - 1]).rstrip(".,;:") + "…"


def _compress(text: str) -> str:
    out = text
    for pattern, repl in _COMPRESS_PHRASES:
        out = pattern.sub(repl, out)
    return _MULTI_SPACE_RE.sub(" ", out).strip(" ,;")


def _rewrite_lead_in(sentence: str) -> str | None:
    s = sentence.strip()
    for pattern, template in _REWRITE_LEAD_INS:
        match = pattern.match(s)
        if not match:
            continue
        payload = match.group(1).strip(" .")
        payload = _compress(payload)
        if not payload:
            continue
        # Keep first letter lowercased payloads readable after prefix.
        rewritten = template.format(payload=payload)
        rewritten = rewritten[0].upper() + rewritten[1:] if rewritten else rewritten
        return _compress(rewritten)
    return None


def _enrich_with_title(summary: str, title: str | None) -> str:
    """Merge useful title tokens (year, product) missing from the summary."""
    if not title:
        return summary
    title_clean = clean_text(title)
    if not title_clean:
        return summary

    # If summary is weak/definition-like, prefer a cleaned title when it looks factual.
    if _is_intro(summary) and _has_news_hint(title_clean):
        return title_clean

    # Inject year from title if summary lacks it.
    years = re.findall(r"\b(20\d{2})\b", title_clean)
    for year in years:
        if year not in summary:
            # "алгоритм SEO продвижения" → "... продвижения сайта на 2026 год"
            summary = re.sub(
                r"(алгоритм\s+(?:seo\s+)?продвижения)",
                rf"\1 сайта на {year} год",
                summary,
                count=1,
                flags=re.IGNORECASE,
            )
            if year not in summary:
                summary = f"{summary.rstrip('.')} ({year})"

    # Prefer "Google/Гугл запускает ..." style from title when body is a definition.
    if "— это" in summary.lower() or "поисковый профиль" in summary.lower()[:40]:
        if _has_news_hint(title_clean):
            # Soft-normalize "Гугл" spelling kept as in title.
            extra = ""
            # Keep Search profile term if present in body.
            m = re.search(r"\(Search profile\)", title_clean + " " + summary, re.I)
            body_bit = ""
            if "авторск" in summary.lower() or "создател" in title_clean.lower():
                body_bit = " для выделения авторского контента"
            # If title already complete enough, use it.
            if len(title_clean) >= 40:
                out = title_clean
                if "search profile" not in out.lower() and m:
                    out = re.sub(
                        r"(профил\w+\s+издателей(?:/создателей контента)?\s+в\s+поиске)",
                        r"\1 (Search profile)",
                        out,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                if body_bit and "авторск" not in out.lower():
                    out = out.rstrip(".") + body_bit
                return _compress(out)
    return summary


def _score_sentence(sentence: str) -> int:
    score = 0
    lower = sentence.lower()
    if _is_intro(sentence):
        return -100
    if _has_news_hint(sentence):
        score += 5
    if re.match(r"^(google|гугл|новая работа|текущая работа|компания|исследовател)", lower):
        score += 4
    if "рассматривает" in lower or "запускает" in lower or "опубликован" in lower:
        score += 3
    if 40 <= len(sentence) <= 220:
        score += 2
    if lower.startswith(("мы ", "я ", "вы ")):
        score -= 3
    return score


def _sumy_summary(text: str, max_sentences: int = 1) -> str | None:
    try:
        from sumy.nlp.tokenizers import Tokenizer
        from sumy.parsers.plaintext import PlaintextParser
        from sumy.summarizers.lsa import LsaSummarizer
    except Exception:  # noqa: BLE001
        return None
    try:
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
    max_len: int = 700,
    max_sentences: int = 3,
    title: str | None = None,
) -> str:
    """Build a factual summary of up to ``max_sentences`` sentences."""
    cleaned = clean_text(text or "")
    title_clean = clean_text(title) if title else ""

    if not cleaned and title_clean:
        return _clip(title_clean, max_len)
    if not cleaned:
        return ""

    if len(cleaned) < 80 and not _is_intro(cleaned):
        return _clip(_enrich_with_title(_compress(cleaned), title_clean), max_len)

    sentences = _split_sentences(cleaned)
    if not sentences:
        sentences = [cleaned]

    scored: list[tuple[int, str]] = []
    seen_norm: set[str] = set()
    for sentence in sentences:
        candidate = _compress(_rewrite_lead_in(sentence) or sentence)
        norm = candidate.lower()
        if not candidate or norm in seen_norm:
            continue
        seen_norm.add(norm)
        scored.append((_score_sentence(candidate), candidate))

    if not scored:
        return _clip(_enrich_with_title(_compress(cleaned), title_clean), max_len)

    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored[0][0] < 0 and title_clean and _has_news_hint(title_clean):
        return _clip(title_clean, max_len)

    keep_n = max(1, int(max_sentences))
    usable = [pair for pair in scored if pair[0] >= 0]
    if not usable:
        usable = scored[:1]
    top = {text for _, text in usable[:keep_n]}
    ordered: list[str] = []
    for sentence in sentences:
        candidate = _compress(_rewrite_lead_in(sentence) or sentence)
        if candidate in top and candidate not in ordered:
            ordered.append(candidate)
        if len(ordered) >= keep_n:
            break
    if not ordered:
        ordered = [usable[0][1]]

    chosen = " ".join(ordered)
    if len(cleaned) > 450:
        sumy_text = _sumy_summary(cleaned, max_sentences=keep_n)
        if sumy_text:
            sumy_clean = clean_text(sumy_text)
            if sumy_clean and _score_sentence(sumy_clean) >= _score_sentence(chosen):
                chosen = sumy_clean

    chosen = _enrich_with_title(_compress(chosen), title_clean)
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
        rewritten = _rewrite_lead_in(line)
        if rewritten:
            return _clip(rewritten, max_len)
        if _is_intro(line):
            continue
        return _clip(line, max_len)
    # Fall back to full summarizer.
    return _clip(clean_and_summarize(cleaned, max_len=max_len), max_len)
