"""Resolve richer display summaries from session events."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SessionEvent
from app.services.memory.citation_parser import parse_summary_tags
from app.services.narration_tags import parse_narration_tags

_NARRATION_TAG_RE = re.compile(r"\[\[P:[a-z_]+(?::.*?(?:\]\]|$))?", re.IGNORECASE)
_APPLIED_CITATION_RE = re.compile(
    r"\s*(?:Applied:\s*)?\[(?:M|G|R):[a-f0-9]{3,8}[^\]]*\]?",
    re.IGNORECASE,
)
_FEEDBACK_RE = re.compile(r"\[\[F:.*?(?:\]\]|$)", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"\[\[S:.*?(?:\]\]|$)", re.IGNORECASE)
_HEARTBEAT_PREFIX_RE = re.compile(r"^\s*HEARTBEAT_(?:OK|ACTION)\s*-?\s*", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_EMPTY_FRAGMENT_RE = re.compile(r"^[\[\]{}\(\)…\s.,;:]*$")
_MARKDOWN_RE = re.compile(r"[*_`#]+")
_COMMAND_START_RE = re.compile(
    r"^(?:now|next|then|let me|let's|run|use|apply|check|inspect|review|verify|commit|publish|open)\b",
    re.IGNORECASE,
)
_RESULT_SIGNAL_RE = re.compile(
    r"\b(?:done|pass(?:es|ed)?|clean|fixed?|implemented?|refactor(?:ed)?|reduced?|moved?|removed?|verified?|completed?|ready)\b",
    re.IGNORECASE,
)
_CONFIDENCE_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[:\-]\s*")
_UNRESOLVED_BLOCKER_RE = re.compile(
    r"\b(?:blocked because|is blocked|was blocked|unavailable|needs manual|requires manual|waiting on)\b",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class SessionDisplaySummaryCandidate:
    """Session metadata used to choose a richer display summary."""

    session_id: str
    summary_oneliner: str | None = None
    live_summary: str | None = None


@dataclass(slots=True, frozen=True)
class SessionDisplaySummaryResult:
    """Resolved display summary plus whether it came from an explicit [[S:...]] tag."""

    summary: str | None
    has_summary_tag: bool
    summary_outcome: str | None = None
    has_unresolved_blocker: bool = False


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text.strip()).lower()


def _is_prompt_like_text(text: str | None) -> bool:
    normalized = _normalize_text(text)
    return (
        "# persona safety boundaries" in normalized
        or "<persona_context>" in normalized
        or "<heartbeat_instructions>" in normalized
        or (text is not None and len(text) > 900 and text.count("\n") > 20)
    )


def _is_generic_status_text(text: str | None) -> bool:
    normalized = _normalize_text(text)
    return normalized in {
        "execution completed",
        "session started",
        "new message",
        "tool",
    } or normalized.startswith("waiting for model after")


def clean_display_summary_text(text: str | None) -> str | None:
    """Strip observability tags and placeholder fragments from display text."""
    if not text:
        return None

    cleaned = (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u2014", "-")
        .replace("\u2013", "-")
    )
    cleaned = _NARRATION_TAG_RE.sub(" ", cleaned)
    cleaned = _APPLIED_CITATION_RE.sub(" ", cleaned)
    cleaned = _FEEDBACK_RE.sub(" ", cleaned)
    cleaned = _SUMMARY_RE.sub(" ", cleaned)
    cleaned = _HEARTBEAT_PREFIX_RE.sub(" ", cleaned)
    cleaned = (
        cleaned
        .replace("\u2026", "...")
        .replace("[...", "")
        .replace("[[", "")
        .replace("]]", "")
    )
    cleaned = _MARKDOWN_RE.sub("", cleaned)
    cleaned = cleaned.replace("\n\n", " ")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if not cleaned or _EMPTY_FRAGMENT_RE.fullmatch(cleaned):
        return None
    return cleaned


def _join_summary_parts(parts: Sequence[str | None]) -> str | None:
    unique_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = _normalize_text(part)
        if not normalized or normalized in seen:
            continue
        cleaned_part = part.strip() if part else ""
        if not cleaned_part:
            continue
        seen.add(normalized)
        unique_parts.append(cleaned_part)
    if not unique_parts:
        return None
    return " ".join(unique_parts)


def _truncate_summary(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_period = truncated.rfind(". ")
    if last_period > max_chars // 2:
        return truncated[: last_period + 1]
    return truncated[: max_chars - 3].rstrip() + "..."


def _sentence_candidates(text: str) -> list[str]:
    candidates = re.split(r"(?<=[.!?])\s+|\s{2,}|\n+", text)
    return [candidate.strip(" -") for candidate in candidates if candidate.strip(" -")]


def _is_command_like_sentence(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return True
    if _COMMAND_START_RE.match(text):
        return True
    if any(token in normalized for token in (" now commit ", " run ", " use ", " let me ")):
        return True
    return "`" in text and any(token in normalized for token in ("commit", "git", "dt ", "st "))


def extract_outcome_summary(text: str | None, *, max_chars: int = 150) -> str | None:
    """Return a concise outcome-focused summary from noisy assistant text."""
    cleaned = clean_display_summary_text(text)
    if not cleaned:
        return None
    cleaned = _CONFIDENCE_PREFIX_RE.sub("", cleaned)
    if _is_prompt_like_text(cleaned) or _is_generic_status_text(cleaned):
        return None

    candidates = _sentence_candidates(cleaned)
    scored: list[tuple[int, int, str]] = []
    for index, candidate in enumerate(candidates):
        if len(candidate.split()) < 3 and len(candidates) > 1 and len(candidate) < 12:
            continue
        if _is_command_like_sentence(candidate):
            continue
        score = 0
        if _RESULT_SIGNAL_RE.search(candidate):
            score += 3
        if 20 <= len(candidate) <= max_chars:
            score += 1
        if index == 0:
            score += 1
        scored.append((score, index, candidate))

    if scored:
        score, index, candidate = max(scored, key=lambda item: (item[0], -item[1]))
        del score, index
        return _truncate_summary(candidate, max_chars)

    return _truncate_summary(cleaned, max_chars)


def _preferred_narration_parts(content: str) -> list[str]:
    tags = parse_narration_tags(content)
    if not tags:
        return []

    parts: list[str] = []
    seen: set[str] = set()
    for tag_type in ("started", "found", "tested", "modified", "decision", "blocked", "confidence"):
        for tag in reversed(tags):
            if tag.tag_type != tag_type:
                continue
            part = extract_outcome_summary(tag.content)
            normalized = _normalize_text(part)
            if not part or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            parts.append(part)
            break
        if len(parts) >= 3:
            break
    return parts


def _build_narration_aware_summary(content: str) -> str | None:
    narration_parts = _preferred_narration_parts(content)
    assistant_text = extract_outcome_summary(content)
    return _join_summary_parts([*narration_parts, assistant_text])


def has_unresolved_completed_summary(text: str | None) -> bool:
    """Return True when a 'completed' summary still describes an unresolved blocker."""
    cleaned = clean_display_summary_text(text)
    if not cleaned:
        return False
    return bool(_UNRESOLVED_BLOCKER_RE.search(cleaned))


def select_display_summary(
    assistant_messages: Sequence[str | None],
    *,
    summary_oneliner: str | None = None,
    live_summary: str | None = None,
) -> str | None:
    """Prefer the latest inline [[S:...]] description, then a clean fallback."""
    return resolve_display_summary(
        assistant_messages,
        summary_oneliner=summary_oneliner,
        live_summary=live_summary,
    ).summary


def resolve_display_summary(
    assistant_messages: Sequence[str | None],
    *,
    summary_oneliner: str | None = None,
    live_summary: str | None = None,
) -> SessionDisplaySummaryResult:
    """Resolve display summary details for one session."""
    latest_summary_tag: str | None = None
    latest_summary_outcome: str | None = None
    latest_meaningful_message: str | None = None

    for content in assistant_messages:
        if not content:
            continue

        if latest_summary_tag is None:
            parsed = parse_summary_tags(content)
            if parsed.tags:
                latest_summary_outcome = parsed.tags[-1].outcome
                latest_summary_tag = clean_display_summary_text(parsed.tags[-1].description)

        if latest_meaningful_message is None:
            cleaned_message = _build_narration_aware_summary(content)
            if (
                cleaned_message
                and not _is_prompt_like_text(cleaned_message)
                and not _is_generic_status_text(cleaned_message)
            ):
                latest_meaningful_message = cleaned_message

        if latest_summary_tag and latest_meaningful_message:
            break

    for candidate in (
        latest_summary_tag,
        latest_meaningful_message,
        clean_display_summary_text(summary_oneliner),
        clean_display_summary_text(live_summary),
    ):
        if candidate and not _is_generic_status_text(candidate):
            return SessionDisplaySummaryResult(
                summary=candidate,
                has_summary_tag=latest_summary_tag is not None,
                summary_outcome=latest_summary_outcome,
                has_unresolved_blocker=(
                    latest_summary_outcome == "completed"
                    and has_unresolved_completed_summary(candidate)
                ),
            )
    return SessionDisplaySummaryResult(
        summary=None,
        has_summary_tag=False,
        summary_outcome=None,
        has_unresolved_blocker=False,
    )


async def fetch_session_display_summaries(
    db: AsyncSession,
    candidates: Sequence[SessionDisplaySummaryCandidate],
) -> dict[str, str | None]:
    """Resolve display summaries for a set of sessions."""
    results = await fetch_session_display_summary_results(db, candidates)
    return {
        session_id: result.summary
        for session_id, result in results.items()
    }


async def fetch_session_display_summary_results(
    db: AsyncSession,
    candidates: Sequence[SessionDisplaySummaryCandidate],
) -> dict[str, SessionDisplaySummaryResult]:
    """Resolve display summary details for a set of sessions."""
    if not candidates:
        return {}

    session_ids = [candidate.session_id for candidate in candidates]
    rows = (
        await db.execute(
            select(SessionEvent.session_id, SessionEvent.content)
            .where(
                SessionEvent.session_id.in_(session_ids),
                SessionEvent.event_type == "assistant_message",
            )
            .order_by(
                SessionEvent.session_id,
                SessionEvent.turn.desc(),
                SessionEvent.sequence.desc(),
            )
        )
    ).all()

    messages_by_session: dict[str, list[str | None]] = {
        candidate.session_id: [] for candidate in candidates
    }
    for session_id, content in rows:
        messages_by_session.setdefault(session_id, []).append(content)

    return {
        candidate.session_id: resolve_display_summary(
            messages_by_session.get(candidate.session_id, []),
            summary_oneliner=candidate.summary_oneliner,
            live_summary=candidate.live_summary,
        )
        for candidate in candidates
    }
