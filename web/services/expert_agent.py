import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable, List


STOP_WORDS = {
    "и",
    "в",
    "во",
    "на",
    "по",
    "к",
    "для",
    "с",
    "со",
    "о",
    "об",
    "это",
    "как",
    "что",
    "при",
    "или",
    "не",
    "а",
    "но",
    "до",
    "от",
    "из",
    "под",
    "над",
    "у",
    "мы",
    "вы",
    "они",
    "он",
    "она",
    "the",
    "and",
    "for",
    "with",
}

QUALITY_THRESHOLDS = {
    "relevance_score": 0.80,
    "platform_fit_score": 0.85,
    "style_match_score": 0.75,
    "fact_consistency_score": 0.75,
    "readability_score": 0.70,
}


def _clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, float(value)))


def _normalize_space(text_value: str) -> str:
    return re.sub(r"\s+", " ", str(text_value or "")).strip()


def _tokenize(text_value: str) -> List[str]:
    return re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", str(text_value or "").lower(), flags=re.UNICODE)


def _dedupe_phrases(items: Iterable[str], limit: int = 16, min_words: int = 1) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for raw_item in items or []:
        text = _normalize_space(str(raw_item or ""))
        if not text:
            continue
        if len(_tokenize(text)) < min_words:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized


def _chunk_text(text_value: str, chunk_size: int = 900) -> List[str]:
    source = _normalize_space(text_value)
    if not source:
        return []
    if len(source) <= chunk_size:
        return [source]

    chunks: List[str] = []
    remaining = source
    while remaining:
        if len(remaining) <= chunk_size:
            chunks.append(remaining)
            break

        cut_pos = remaining.rfind(". ", 0, chunk_size)
        if cut_pos < int(chunk_size * 0.5):
            cut_pos = remaining.rfind(" ", 0, chunk_size)
        if cut_pos < 100:
            cut_pos = chunk_size

        chunk = remaining[:cut_pos].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut_pos:].strip()

    return chunks


def _top_keywords(text_value: str, limit: int = 10) -> List[str]:
    tokens = _tokenize(text_value)
    filtered = [token for token in tokens if len(token) >= 4 and token not in STOP_WORDS]
    if not filtered:
        return []
    counts = Counter(filtered)
    return [token for token, _ in counts.most_common(limit)]


def _summarize_text(text_value: str, max_len: int = 180) -> str:
    source = _normalize_space(text_value)
    if len(source) <= max_len:
        return source
    cut = source.rfind(". ", 0, max_len)
    if cut < int(max_len * 0.6):
        cut = source.rfind(" ", 0, max_len)
    if cut <= 0:
        cut = max_len
    return source[:cut].rstrip() + "..."


def _infer_intent_type(phrase: str) -> str:
    text = str(phrase or "").lower()
    if any(mark in text for mark in ("сравн", "топ", "vs", "лучш", "обзор")):
        return "comparison"
    if any(mark in text for mark in ("цена", "куп", "скидк", "заказ", "бюджет", "стоим")):
        return "commercial"
    if any(mark in text for mark in ("опрос", "вопрос", "мнение", "обсуд", "история")):
        return "engagement"
    return "informational"


def prepare_knowledge_documents(
    *,
    channel_name: str,
    base_texts: Iterable[str],
    max_documents: int = 40,
) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    chunk_index = 0
    seen = set()

    for raw_text in base_texts or []:
        text = _normalize_space(str(raw_text or ""))
        if len(text) < 24:
            continue
        for chunk in _chunk_text(text):
            if len(chunk) < 24:
                continue
            key = chunk.casefold()
            if key in seen:
                continue
            seen.add(key)
            docs.append(
                {
                    "chunk_index": chunk_index,
                    "text": chunk,
                    "summary": _summarize_text(chunk),
                    "keywords": _top_keywords(chunk, limit=8),
                    "entities": [],
                    "title": f"Knowledge chunk for {channel_name}",
                }
            )
            chunk_index += 1
            if len(docs) >= max_documents:
                return docs

    return docs


def build_semantic_clusters(
    *,
    channel_name: str,
    base_phrases: Iterable[str] = None,
    corpus_text: str = "",
    limit: int = 12,
) -> List[Dict[str, Any]]:
    phrases = _dedupe_phrases(base_phrases or [], limit=limit * 3, min_words=1)
    corpus_keywords = _top_keywords(corpus_text, limit=max(limit * 2, 12))

    # Build compact phrase candidates from corpus keywords.
    keyword_phrases: List[str] = []
    for idx in range(0, len(corpus_keywords), 2):
        pair = corpus_keywords[idx : idx + 2]
        if not pair:
            continue
        keyword_phrases.append(" ".join(pair))
    phrases.extend(keyword_phrases)

    phrases = _dedupe_phrases(phrases, limit=limit, min_words=1)
    if not phrases:
        phrases = [f"Контент-направление канала {channel_name}"]

    clusters: List[Dict[str, Any]] = []
    for idx, phrase in enumerate(phrases, start=1):
        clusters.append(
            {
                "cluster_name": phrase[:240],
                "intent_type": _infer_intent_type(phrase),
                "priority": max(1, 11 - idx),
                "seasonality": "all_year",
            }
        )
    return clusters[:limit]


def build_research_queries(
    *,
    channel_name: str,
    semantic_clusters: Iterable[str] = None,
    focus_text: str = "",
    limit: int = 8,
) -> List[str]:
    year = datetime.utcnow().year
    raw_candidates: List[str] = []
    if focus_text:
        raw_candidates.append(focus_text)
    raw_candidates.append(channel_name)
    raw_candidates.extend([str(item or "") for item in semantic_clusters or []])

    normalized = _dedupe_phrases(raw_candidates, limit=max(limit * 2, 10), min_words=1)
    queries: List[str] = []
    for candidate in normalized:
        queries.append(f"{candidate} {year} вопросы аудитории")
        queries.append(f"{candidate} актуальные вопросы")
        if len(queries) >= limit * 2:
            break

    return _dedupe_phrases(queries, limit=limit, min_words=2)


def build_retrieved_context(
    *,
    semantic_clusters: Iterable[Any] = None,
    audience_questions: Iterable[Any] = None,
    knowledge_documents: Iterable[Any] = None,
    max_clusters: int = 5,
    max_questions: int = 5,
    max_docs: int = 4,
) -> Dict[str, Any]:
    semantic_hints: List[str] = []
    for item in semantic_clusters or []:
        if isinstance(item, dict):
            semantic_hints.append(str(item.get("cluster_name") or "").strip())
        else:
            semantic_hints.append(str(getattr(item, "cluster_name", "") or item or "").strip())
    semantic_hints = _dedupe_phrases(semantic_hints, limit=max_clusters, min_words=1)

    question_hints: List[str] = []
    for item in audience_questions or []:
        if isinstance(item, dict):
            question_hints.append(str(item.get("question_text") or item.get("question") or "").strip())
        else:
            question_hints.append(str(getattr(item, "question_text", "") or item or "").strip())
    question_hints = _dedupe_phrases(question_hints, limit=max_questions, min_words=3)

    doc_hints: List[str] = []
    for item in knowledge_documents or []:
        if isinstance(item, dict):
            summary = str(item.get("summary") or item.get("text") or "").strip()
        else:
            summary = str(getattr(item, "summary", "") or getattr(item, "text", "") or "").strip()
        if summary:
            doc_hints.append(_summarize_text(summary, max_len=180))
    doc_hints = _dedupe_phrases(doc_hints, limit=max_docs, min_words=3)

    lines: List[str] = []
    if semantic_hints:
        lines.append(f"Semantic vectors: {', '.join(semantic_hints)}.")
    if question_hints:
        lines.append(f"Top audience questions: {'; '.join(question_hints)}.")
    if doc_hints:
        lines.append(f"Reference facts: {' | '.join(doc_hints)}.")

    context_block = "\n".join(lines)
    references = [*semantic_hints, *question_hints, *doc_hints]
    return {
        "context_block": context_block,
        "references": references[:30],
        "semantic_hints": semantic_hints,
        "question_hints": question_hints,
        "document_hints": doc_hints,
    }


def _score_relevance(text_value: str, topic: str, semantic_hints: Iterable[str]) -> float:
    text_tokens = set(_tokenize(text_value))
    target_tokens = set(_tokenize(topic))
    for hint in semantic_hints or []:
        target_tokens.update(_tokenize(hint))

    if not target_tokens:
        return 0.75

    overlap = len(text_tokens.intersection(target_tokens)) / max(1, min(len(target_tokens), 18))
    score = 0.25 + overlap
    if str(topic or "").strip() and str(topic).lower() in str(text_value or "").lower():
        score += 0.12
    return _clamp(score)


def _score_platform_fit(text_value: str, platform: str) -> float:
    text_len = len(str(text_value or ""))
    hashtags_count = len(re.findall(r"#\w+", str(text_value or ""), flags=re.UNICODE))
    line_breaks = str(text_value or "").count("\n")
    platform = str(platform or "").strip().lower()

    if platform == "telegram":
        if text_len <= 900:
            score = 0.90
        elif text_len <= 1024:
            score = 0.84
        elif text_len <= 1500:
            score = 0.62
        else:
            score = 0.38
        if line_breaks >= 2:
            score += 0.05
        if hashtags_count > 3:
            score -= 0.05
        return _clamp(score)

    if platform == "vk":
        if 280 <= text_len <= 1800:
            score = 0.88
        elif 180 <= text_len <= 2200:
            score = 0.78
        else:
            score = 0.58
        if 2 <= hashtags_count <= 7:
            score += 0.07
        elif hashtags_count == 0:
            score -= 0.08
        return _clamp(score)

    return 0.75


def _score_style_match(text_value: str) -> float:
    text = str(text_value or "").lower()
    score = 0.82
    banned_phrases = {
        "продвижение магазина": 0.12,
        "продажи любой ценой": 0.15,
        "технические детали llm": 0.12,
        "нейросеть выбрала": 0.08,
        "как работает модель": 0.08,
    }
    for phrase, penalty in banned_phrases.items():
        if phrase in text:
            score -= penalty

    if any(marker in text for marker in ("чек-лист", "совет", "пошаг", "разбор", "как выбрать")):
        score += 0.05
    if any(marker in text for marker in ("сохраните", "попробуйте", "проверьте", "напишите")):
        score += 0.04
    return _clamp(score)


def _score_fact_consistency(text_value: str) -> float:
    text = str(text_value or "").lower()
    score = 0.82
    current_year = datetime.utcnow().year
    years = [int(year) for year in re.findall(r"\b20\d{2}\b", text)]
    if any(year < current_year - 1 for year in years):
        score -= 0.18
    if any(year == current_year for year in years):
        score += 0.05
    if "гарантированно" in text:
        score -= 0.05
    return _clamp(score)


def _split_sentences(text_value: str) -> List[str]:
    parts = [part.strip() for part in re.split(r"[.!?]+", str(text_value or "")) if part.strip()]
    return parts


def _score_readability(text_value: str, platform: str) -> float:
    words_count = len(_tokenize(text_value))
    sentences = _split_sentences(text_value)
    avg_sentence_len = words_count / max(1, len(sentences))
    line_breaks = str(text_value or "").count("\n")

    if words_count < 35:
        score = 0.55
    elif words_count > 420 and platform == "telegram":
        score = 0.58
    else:
        score = 0.76

    if 8 <= avg_sentence_len <= 22:
        score += 0.12
    if 1 <= line_breaks <= 24:
        score += 0.05
    return _clamp(score)


def _resolve_quality_decision(scores: Dict[str, float]) -> str:
    if (
        scores["relevance_score"] < QUALITY_THRESHOLDS["relevance_score"]
        or scores["platform_fit_score"] < QUALITY_THRESHOLDS["platform_fit_score"]
        or scores["fact_consistency_score"] < QUALITY_THRESHOLDS["fact_consistency_score"]
    ):
        if scores["relevance_score"] < 0.65 or scores["fact_consistency_score"] < 0.60:
            return "reject"
        return "revise"

    if (
        scores["style_match_score"] < QUALITY_THRESHOLDS["style_match_score"]
        or scores["readability_score"] < QUALITY_THRESHOLDS["readability_score"]
    ):
        return "revise"

    return "approve"


def _build_risk_flags(scores: Dict[str, float], platform: str, text_value: str) -> List[str]:
    flags: List[str] = []
    if scores["relevance_score"] < QUALITY_THRESHOLDS["relevance_score"]:
        flags.append("low_relevance")
    if scores["platform_fit_score"] < QUALITY_THRESHOLDS["platform_fit_score"]:
        flags.append("platform_format_mismatch")
    if scores["fact_consistency_score"] < QUALITY_THRESHOLDS["fact_consistency_score"]:
        flags.append("fact_freshness_risk")
    if scores["style_match_score"] < QUALITY_THRESHOLDS["style_match_score"]:
        flags.append("style_mismatch")
    if scores["readability_score"] < QUALITY_THRESHOLDS["readability_score"]:
        flags.append("readability_low")

    if platform == "telegram" and len(str(text_value or "")) > 1024:
        flags.append("telegram_length_overflow")
    return flags


def evaluate_draft_quality(
    *,
    text_value: str,
    topic: str,
    platform: str,
    semantic_hints: Iterable[str] = None,
    audience_questions: Iterable[str] = None,
) -> Dict[str, Any]:
    text_value = str(text_value or "").strip()
    topic = str(topic or "").strip()
    platform = str(platform or "").strip().lower()
    semantic_hints = [str(item or "").strip() for item in semantic_hints or [] if str(item or "").strip()]
    audience_questions = [str(item or "").strip() for item in audience_questions or [] if str(item or "").strip()]

    enriched_hints = [*semantic_hints, *audience_questions]
    relevance_score = _score_relevance(text_value, topic, enriched_hints)
    platform_fit_score = _score_platform_fit(text_value, platform)
    style_match_score = _score_style_match(text_value)
    fact_consistency_score = _score_fact_consistency(text_value)
    readability_score = _score_readability(text_value, platform)

    scores = {
        "relevance_score": round(relevance_score, 4),
        "platform_fit_score": round(platform_fit_score, 4),
        "style_match_score": round(style_match_score, 4),
        "fact_consistency_score": round(fact_consistency_score, 4),
        "readability_score": round(readability_score, 4),
    }
    quality_score = (
        relevance_score * 0.30
        + platform_fit_score * 0.22
        + style_match_score * 0.18
        + fact_consistency_score * 0.20
        + readability_score * 0.10
    )
    decision = _resolve_quality_decision(scores)
    risk_flags = _build_risk_flags(scores, platform, text_value)

    return {
        **scores,
        "quality_score": round(_clamp(quality_score), 4),
        "decision": decision,
        "risk_flags": risk_flags,
        "thresholds": QUALITY_THRESHOLDS.copy(),
    }
