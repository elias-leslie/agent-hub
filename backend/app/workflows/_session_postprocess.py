"""Shared session post-processing helpers for summaries."""

from __future__ import annotations

import logging
import re

from app.services.memory.citation_parser import normalize_terminal_summary_tag, parse_summary_tags
from app.services.narration_tags import parse_narration_tags
from app.services.session_display_summary import has_unresolved_completed_summary

logger = logging.getLogger(__name__)

_SUMMARY_AT_END_RE = re.compile(r"\[\[S:(completed|partial|failed):(.*?)\]\]\s*$", re.IGNORECASE | re.DOTALL)
_COMMANDY_SUMMARY_RE = re.compile(
    r"^(?:now|next|then|let me|let's|run|use|check|verify|commit|publish|open|inspect)\b",
    re.IGNORECASE,
)
_PROGRESS_EVIDENCE_TAGS = frozenset({"modified", "tested", "blocked", "decision", "confidence"})
_PROGRESS_TAG_WITH_TRAILING_TEXT_RE = re.compile(r"\[\[P:[a-z_]+:(.*?)\]\]\s*([^\[]+)", re.IGNORECASE | re.DOTALL)


def has_inline_summary_tag(content: str | None) -> bool:
    """Return True when content includes an inline [[S:...]] summary tag."""
    if not content:
        return False
    return bool(parse_summary_tags(content).tags)


def inline_summary_contract_issues(content: str | None) -> list[str]:
    """Return contract issues for the inline [[S:...]] closeout summary."""
    if not content:
        return ["missing inline [[S:...]] summary tag"]

    normalized_content = normalize_terminal_summary_tag(content)
    parsed = parse_summary_tags(normalized_content).tags
    if not parsed:
        return ["missing inline [[S:...]] summary tag"]

    issues: list[str] = []
    if not _SUMMARY_AT_END_RE.search(normalized_content):
        issues.append("inline summary tag is not the final line")

    last_description = parsed[-1].description.strip()
    if len(last_description) < 12:
        issues.append("inline summary tag is too short to be useful")
    if "\n" in last_description:
        issues.append("inline summary tag must stay single-line")
    if _COMMANDY_SUMMARY_RE.match(last_description):
        issues.append("inline summary tag is procedural instead of outcome-focused")
    if parsed[-1].outcome == "completed" and has_unresolved_completed_summary(last_description):
        issues.append("completed inline summary tag still describes an unresolved blocker")
    return issues


def progress_tag_contract_issues(
    content: str | None,
    *,
    require_progress: bool,
) -> list[str]:
    """Return contract issues for in-flight [[P:...]] narration tags."""
    if not require_progress:
        return []

    tags = parse_narration_tags(content or "")
    if not tags:
        return ["missing [[P:...]] progress tags on task session"]

    tag_types = {tag.tag_type for tag in tags}
    issues: list[str] = []
    if len(tags) < 2:
        issues.append("task session has fewer than 2 progress tags")
    if not ({"started", "found"} & tag_types):
        issues.append("task session is missing an initial progress tag")
    if not (_PROGRESS_EVIDENCE_TAGS & tag_types):
        issues.append("task session is missing a later proof/decision/blocker progress tag")
    if _has_mirrored_progress_text(content or ""):
        issues.append("progress tag content is duplicated in surrounding prose")
    return issues


def _normalize_contract_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _has_mirrored_progress_text(content: str) -> bool:
    """Return True when free text simply mirrors an adjacent progress tag."""
    for match in _PROGRESS_TAG_WITH_TRAILING_TEXT_RE.finditer(content):
        tag_text = _normalize_contract_text(match.group(1))
        trailing = match.group(2).strip()
        if not trailing:
            continue
        trailing_first = re.split(r"[.\n]+", trailing, maxsplit=1)[0]
        trailing_text = _normalize_contract_text(trailing_first)
        if not tag_text or not trailing_text:
            continue
        if trailing_text == tag_text or trailing_text.startswith(tag_text) or tag_text.startswith(trailing_text):
            return True
    return False


async def ensure_session_summary(
    session_id: str,
    content: str,
    *,
    agent_id: str | None = None,
    empty_fallback: str = "Session completed (no output)",
) -> bool:
    """Ensure the session has a summary via inline tags or a synthetic fallback."""
    try:
        from app.api.complete.citation_tracker import track_inline_summaries
        from app.db import async_session

        async with async_session() as db:
            stored = await track_inline_summaries(content, db, session_id, agent_id=agent_id)
            if stored:
                await db.commit()

        if stored:
            return True

        summary = extract_synthetic_summary(content)
        if not summary:
            from app.services.memory.summary_generator import generate_session_summary

            generated = await generate_session_summary(session_id)
            if not generated.skipped and generated.summary:
                return True
            summary = empty_fallback

        from app.services.memory.summary_generator import store_summary_on_session

        await store_summary_on_session(
            session_id=session_id,
            summary_oneliner=summary,
            outcome="completed",
            files_touched=[],
            git_digest="",
        )
        return True
    except Exception:
        logger.exception("Failed to ensure session summary for %s", session_id)
        return False


def extract_synthetic_summary(content: str) -> str:
    """Extract a concise synthetic summary from model output."""
    from app.services.session_display_summary import extract_outcome_summary

    if not content or not content.strip():
        return ""

    text = content.strip()
    for prefix in ("HEARTBEAT_OK", "HEARTBEAT_ACTION"):
        if text.startswith(prefix):
            after = text[len(prefix):].lstrip(" \u2014\u2013-").strip()
            if after:
                summary = extract_outcome_summary(after, max_chars=120)
                if summary:
                    return summary
            return prefix.lower().replace("_", " ")

    return extract_outcome_summary(text, max_chars=120) or ""
