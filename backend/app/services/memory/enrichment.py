"""Low-risk memory enrichment used at capture time."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .budget import count_tokens

_ACTION_RE = re.compile(
    r"\b(?:todo|follow[- ]?up|next|fix|implement|add|remove|review|verify|schedule)\b",
    re.IGNORECASE,
)
_DECISION_RE = re.compile(r"\b(?:decided|decision|use|adopt|prefer|must|never)\b", re.IGNORECASE)
_PRIVATE_RE = re.compile(
    r"\b(?:api[_-]?key|secret|token|password|ssn|social security|private key)\b",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b")
_TOPIC_RE = re.compile(r"\b[a-z][a-z0-9_-]{3,}\b", re.IGNORECASE)
_STOPWORDS = {
    "about",
    "after",
    "agent",
    "before",
    "content",
    "context",
    "from",
    "have",
    "memory",
    "need",
    "that",
    "this",
    "with",
}


@dataclass(frozen=True)
class MemoryEnrichment:
    """Derived metadata for a captured memory."""

    summary: str | None
    sensitivity_tier: str = "normal"
    importance: int = 2
    quality_score: float = 0.5
    topics: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


def _first_sentence(text: str, *, max_chars: int = 120) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
    if len(sentence) <= max_chars:
        return sentence
    return sentence[: max_chars - 1].rstrip() + "..."


def _extract_topics(text: str, *, limit: int = 8) -> list[str]:
    counts: dict[str, int] = {}
    for match in _TOPIC_RE.finditer(text):
        topic = match.group(0).lower()
        if topic in _STOPWORDS or topic.isdigit():
            continue
        counts[topic] = counts.get(topic, 0) + 1
    return [
        topic for topic, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _extract_action_items(text: str, *, limit: int = 5) -> list[str]:
    items: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip(" -*\t")
        if not line or not _ACTION_RE.search(line):
            continue
        items.append(line[:180])
        if len(items) >= limit:
            break
    return items


def _sensitivity_tier(text: str) -> str:
    if _PRIVATE_RE.search(text):
        return "confidential"
    if _EMAIL_RE.search(text):
        return "personal"
    return "normal"


def enrich_memory_content(
    content: str,
    *,
    source: str | None = None,
    observation_type: str | None = None,
    summary: str | None = None,
) -> MemoryEnrichment:
    """Return compact deterministic enrichment for a memory candidate."""
    topics = _extract_topics(content)
    action_items = _extract_action_items(content)
    token_count = count_tokens(content)
    has_decision = bool(_DECISION_RE.search(content))
    importance = 3 if has_decision or action_items else 2
    if token_count > 1200:
        importance += 1
    quality_score = min(1.0, 0.35 + (0.1 if topics else 0) + (0.2 if has_decision else 0) + (0.15 if action_items else 0))
    resolved_summary = summary or _first_sentence(content, max_chars=120) or None
    metadata: dict[str, object] = {
        "enrichment": {
            "source": source,
            "observation_type": observation_type,
            "topics": topics,
            "action_items": action_items,
            "importance": importance,
            "quality_score": round(quality_score, 2),
            "token_count": token_count,
        }
    }
    return MemoryEnrichment(
        summary=resolved_summary,
        sensitivity_tier=_sensitivity_tier(content),
        importance=importance,
        quality_score=round(quality_score, 2),
        topics=topics,
        action_items=action_items,
        metadata=metadata,
    )
