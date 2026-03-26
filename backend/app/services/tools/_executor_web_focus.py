"""BM25 focus selection for web content chunks."""
from __future__ import annotations

import re


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _tokenize_focus_text(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def _split_long_block(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", block) if s.strip()]
    if len(sentences) <= 1:
        return [block[i : i + max_chars].strip() for i in range(0, len(block), max_chars)]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        sentence_len = len(sentence) + (1 if current else 0)
        if current and current_len + sentence_len > max_chars:
            chunks.append(" ".join(current).strip())
            current = [sentence]
            current_len = len(sentence)
            continue
        current.append(sentence)
        current_len += sentence_len
    if current:
        chunks.append(" ".join(current).strip())
    return chunks


def _build_focus_chunks(content: str) -> list[tuple[int, str]]:
    raw_blocks = [block.strip() for block in re.split(r"\n\s*\n+", content) if block.strip()]
    if not raw_blocks:
        normalized = content.strip()
        return [(0, normalized)] if normalized else []

    chunks: list[str] = []
    index = 0
    while index < len(raw_blocks):
        block = raw_blocks[index]
        if index + 1 < len(raw_blocks) and len(block) <= 120 and (
            block.startswith("#") or "\n" not in block
        ):
            block = f"{block}\n\n{raw_blocks[index + 1]}"
            index += 2
        else:
            index += 1
        chunks.extend(_split_long_block(block, max_chars=1200))

    return [(i, chunk) for i, chunk in enumerate(chunks) if chunk.strip()]


def _score_chunks(chunks: list[tuple[int, str]], query_terms: list[str]) -> list[float]:
    from rank_bm25 import BM25Okapi

    chunk_terms = [_tokenize_focus_text(chunk) for _, chunk in chunks]
    if not any(chunk_terms):
        return []
    return list(BM25Okapi(chunk_terms).get_scores(query_terms))


def _select_chunk_indices(
    chunks: list[tuple[int, str]], scores: list[float], max_chars: int
) -> list[int]:
    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    selected: list[int] = []
    selected_chars = 0
    for idx in ranked:
        chunk_text = chunks[idx][1]
        score = float(scores[idx])
        if not chunk_text.strip() or score <= 0:
            continue
        projected = selected_chars + len(chunk_text) + (2 if selected else 0)
        if selected and projected > max_chars:
            continue
        selected.append(idx)
        selected_chars = projected
        if selected_chars >= max_chars:
            break
    selected.sort(key=lambda i: chunks[i][0])
    return selected


def _select_focused_content(
    content: str,
    focus_query: str | None,
    max_chars: int,
) -> tuple[str, dict[str, object]]:
    stripped_content = content.strip()
    normalized_query = _normalize_whitespace(focus_query or "")
    if not normalized_query or not stripped_content:
        return content, {"focused": False}

    chunks = _build_focus_chunks(stripped_content)
    query_terms = _tokenize_focus_text(normalized_query)
    if not chunks or not query_terms:
        return content, {"focused": False}

    scores = _score_chunks(chunks, query_terms)
    if not scores:
        return content, {"focused": False}

    selected = _select_chunk_indices(chunks, scores, max_chars)
    if not selected:
        return content, {"focused": False}

    focused = "\n\n".join(chunks[i][1] for i in selected).strip()
    if not focused:
        return content, {"focused": False}

    return focused, {
        "focused": focused != stripped_content,
        "focus_query": normalized_query,
        "focus_strategy": "bm25_chunks",
        "selected_chunk_count": len(selected),
        "candidate_chunk_count": len(chunks),
    }
