"""Shared session post-processing helpers for summaries."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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
            return True

        summary = extract_synthetic_summary(content)
        if not summary:
            from app.services.memory.summary_generator import generate_session_summary

            generated = await generate_session_summary(session_id)
            if not generated.skipped and generated.summary:
                return True
            summary = empty_fallback

        from app.services.memory.summary_generator import _store_summary_on_session

        await _store_summary_on_session(
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
    if not content or not content.strip():
        return ""

    text = content.strip()
    for prefix in ("HEARTBEAT_OK", "HEARTBEAT_ACTION"):
        if text.startswith(prefix):
            after = text[len(prefix):].lstrip(" \u2014\u2013-").strip()
            if after:
                period_idx = after.find(". ")
                if 0 < period_idx <= 120:
                    return after[: period_idx + 1]
                return after[:120].rstrip() + ("..." if len(after) > 120 else "")
            return prefix.lower().replace("_", " ")

    return text[:120].rstrip() + ("..." if len(text) > 120 else "")
