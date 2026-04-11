"""Strict Caveman compactness checks for prompt and memory authoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ContentKind = Literal["prompt", "memory"]

FILLER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("just", re.compile(r"\bjust\b", re.IGNORECASE)),
    ("really", re.compile(r"\breally\b", re.IGNORECASE)),
    ("basically", re.compile(r"\bbasically\b", re.IGNORECASE)),
    ("please", re.compile(r"\bplease\b", re.IGNORECASE)),
    ("let me know", re.compile(r"\blet me know\b", re.IGNORECASE)),
    ("feel free", re.compile(r"\bfeel free\b", re.IGNORECASE)),
    ("i recommend", re.compile(r"\bi recommend\b", re.IGNORECASE)),
    ("i suggest", re.compile(r"\bi suggest\b", re.IGNORECASE)),
    ("you should", re.compile(r"\byou should\b", re.IGNORECASE)),
    ("make sure", re.compile(r"\bmake sure\b", re.IGNORECASE)),
)
EXAMPLE_PATTERN = re.compile(r"\bfor example\b|\be\.g\.\b|example:", re.IGNORECASE)
HEDGE_PATTERN = re.compile(
    r"\b(?:maybe|probably|likely|might|could|should|usually|generally|try to)\b",
    re.IGNORECASE,
)
SOFT_TONE_PATTERN = re.compile(
    r"\b(?:be thorough|be objective|be specific|be precise|be natural|be conversational|be helpful|be friendly|be confident)\b",
    re.IGNORECASE,
)
OFFER_BACK_PATTERN = re.compile(
    r"\b(?:if you want|would you like|happy to help|happy to|let me know if)\b",
    re.IGNORECASE,
)
PROSE_CODE_BLOCK_PATTERN = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_PATTERN = re.compile(r"`[^`]*`")
PLACEHOLDER_PATTERN = re.compile(r"\{[^{}\n]+\}")
WORD_PATTERN = re.compile(r"[A-Za-z']+")
ARTICLE_WORDS = {"a", "an", "the"}


@dataclass(frozen=True)
class CompactnessReport:
    kind: ContentKind
    chars: int
    lines: int
    tokens: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


class CompactnessValidationError(Exception):
    """Raised when content violates the strict Caveman gate."""

    def __init__(self, kind: ContentKind, errors: list[str]):
        self.kind = kind
        self.errors = tuple(errors)
        detail = "; ".join(errors)
        super().__init__(f"{kind} failed strict Caveman gate: {detail}")


def _line_count(content: str) -> int:
    return content.count("\n") + (1 if content and not content.endswith("\n") else 0)


def _estimate_tokens(content: str) -> int:
    return 0 if not content else max(1, len(content) // 4)


def _detect_fillers(content: str) -> list[str]:
    return [label for label, pattern in FILLER_PATTERNS if pattern.search(content)]


def _strip_non_prose(content: str) -> str:
    stripped = PROSE_CODE_BLOCK_PATTERN.sub(" ", content)
    stripped = INLINE_CODE_PATTERN.sub(" ", stripped)
    stripped = PLACEHOLDER_PATTERN.sub(" ", stripped)
    stripped = re.sub(r"(?m)^\s{0,3}#+\s*", "", stripped)
    stripped = re.sub(r"(?m)^\s*[-*]\s+", "", stripped)
    stripped = re.sub(r"(?m)^\s*\d+\.\s+", "", stripped)
    return stripped


def _extract_sentences(content: str) -> list[str]:
    prose = _strip_non_prose(content)
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", prose)
        if WORD_PATTERN.search(sentence)
    ]


def _article_ratio(words: list[str]) -> float:
    if not words:
        return 0.0
    article_count = sum(1 for word in words if word in ARTICLE_WORDS)
    return article_count / len(words)


def analyze_compactness(content: str, *, kind: ContentKind) -> CompactnessReport:
    chars = len(content)
    lines = _line_count(content)
    tokens = _estimate_tokens(content)
    errors: list[str] = []
    warnings: list[str] = []
    filler_hits = _detect_fillers(content)
    sentences = _extract_sentences(content)
    prose_words = WORD_PATTERN.findall(_strip_non_prose(content).lower())
    article_ratio = _article_ratio(prose_words)

    if kind == "prompt":
        if tokens > 350:
            warnings.append(f"large prompt ({tokens} tok). Hot-path prompts pay this every turn.")
        if lines > 80:
            warnings.append(f"long prompt ({lines} lines). Collapse repeated examples and overlap.")
    else:
        if chars > 280:
            warnings.append(f"long memory ({chars} chars). Keep one atomic rule; split if needed.")
        if lines > 4:
            warnings.append(f"multi-line memory ({lines} lines). Prefer one short rule body.")

    if filler_hits:
        errors.append(f"filler terms found: {', '.join(filler_hits[:4])}")

    if EXAMPLE_PATTERN.search(content):
        errors.append("example markers found. Strip examples; keep direct rules only.")

    if HEDGE_PATTERN.search(content):
        errors.append("hedging found. Replace maybe/should/could-style phrasing with direct rules.")

    if SOFT_TONE_PATTERN.search(content):
        errors.append("soft-tone phrasing found. Replace 'be X' guidance with direct action rules.")

    if OFFER_BACK_PATTERN.search(content):
        errors.append("offer-back phrasing found. Remove optional follow-up or helper language.")

    if prose_words and len(prose_words) >= 80 and article_ratio > 0.085:
        errors.append(
            f"article-heavy prose ({article_ratio:.1%}). Drop articles and compress sentence shape."
        )

    long_sentences = [sentence for sentence in sentences if len(WORD_PATTERN.findall(sentence)) > 24]
    if long_sentences:
        errors.append("long prose sentences found. Split into short direct lines or bullets.")

    if sentences:
        average_sentence_words = sum(len(WORD_PATTERN.findall(sentence)) for sentence in sentences) / len(sentences)
        if len(prose_words) >= 120 and average_sentence_words > 16:
            errors.append(
                f"average sentence too long ({average_sentence_words:.1f} words). Compress prose."
            )

    return CompactnessReport(
        kind=kind,
        chars=chars,
        lines=lines,
        tokens=tokens,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def validate_compactness(content: str, *, kind: ContentKind) -> CompactnessReport:
    report = analyze_compactness(content, kind=kind)
    if report.errors:
        raise CompactnessValidationError(kind, list(report.errors))
    return report
