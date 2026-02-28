"""Post-heartbeat lifecycle — guaranteed summaries, journaling, and format validation.

Runs after complete_internal() returns, ensuring outcomes that Jenny's voluntary
behavior alone cannot guarantee. This is the structural fix for findings 1, 2, 5, 7.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.api.complete.types import CompletionInternalResult

logger = logging.getLogger(__name__)


async def postprocess_heartbeat(
    result: CompletionInternalResult,
    interval_minutes: int,
):
    """Post-process heartbeat: summaries, journaling, format validation.

    Returns a HeartbeatResult instance.
    """
    from app.workflows.persona_heartbeat import HeartbeatResult

    content = result.content or ""
    session_id = result.session_id

    # 1. Summary extraction (Finding 1)
    summary_stored = await _ensure_session_summary(session_id, content)

    # 2. Auto-journaling (Finding 2)
    auto_journaled = await _auto_journal_if_needed(session_id, content, result.error)

    # 3. Format validation (Finding 7)
    status, format_ok = _validate_heartbeat_format(content)

    # 4. Record observability metrics (Finding 6)
    from app.workflows._heartbeat_redis import record_heartbeat_metrics

    await record_heartbeat_metrics(
        format_compliant=format_ok,
        summary_stored=summary_stored,
        auto_journaled=auto_journaled,
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        had_error=result.error is not None,
    )

    return HeartbeatResult(
        status=status,
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        interval_minutes=interval_minutes,
        error=result.error,
        format_compliant=format_ok,
        summary_stored=summary_stored,
        auto_journaled=auto_journaled,
    )


async def _ensure_session_summary(session_id: str, content: str) -> bool:
    """Ensure the session has a summary — from inline tags or synthetic fallback."""
    try:
        from app.api.complete.citation_tracker import track_inline_summaries
        from app.db import async_session

        async with async_session() as db:
            stored = await track_inline_summaries(content, db, session_id, agent_id="persona")

        if stored:
            return True

        # No [[S:...]] tag — generate synthetic summary
        summary = _extract_synthetic_summary(content)
        if summary:
            from app.services.memory.summary_generator import _store_summary_on_session

            await _store_summary_on_session(
                session_id=session_id,
                summary_oneliner=summary,
                outcome="completed",
                files_touched=[],
                git_digest="",
            )
            return True

        return False
    except Exception:
        logger.exception("Failed to ensure session summary for %s", session_id)
        return False


def _extract_synthetic_summary(content: str) -> str:
    """Extract a synthetic summary from heartbeat output.

    Parses HEARTBEAT_OK/HEARTBEAT_ACTION prefix and extracts the sentence after it.
    Falls back to first 120 chars of content.
    """
    if not content or not content.strip():
        return ""

    text = content.strip()

    # Try to extract from HEARTBEAT_OK/HEARTBEAT_ACTION prefix
    for prefix in ("HEARTBEAT_OK", "HEARTBEAT_ACTION"):
        if text.startswith(prefix):
            after = text[len(prefix):].lstrip(" \u2014\u2013-").strip()
            if after:
                # Take first sentence or up to 120 chars
                period_idx = after.find(". ")
                if 0 < period_idx <= 120:
                    return after[: period_idx + 1]
                return after[:120].rstrip() + ("..." if len(after) > 120 else "")
            return prefix.lower().replace("_", " ")

    # Fallback: first 120 chars
    return text[:120].rstrip() + ("..." if len(text) > 120 else "")


async def _auto_journal_if_needed(
    session_id: str,
    content: str,
    error: str | None,
) -> bool:
    """Auto-journal if Jenny didn't journal during this heartbeat session."""
    try:
        from sqlalchemy import text

        from app.db import async_session

        # Check if Jenny already wrote a journal entry in this session
        async with async_session() as db:
            result = await db.execute(
                text(
                    "SELECT id FROM session_events"
                    " WHERE session_id = :sid AND event_type = 'tool_use'"
                    " AND tool_name = 'write_journal' LIMIT 1"
                ),
                {"sid": session_id},
            )
            jenny_journaled = result.scalar_one_or_none() is not None

        if jenny_journaled and not error:
            return False

        # Auto-journal: either she skipped or there was an error
        from app.services.tools._executor_persona import write_journal

        if error:
            await write_journal(f"[auto] Heartbeat error: {error}", "observation")
        elif content and content.strip():
            summary = _extract_synthetic_summary(content)
            await write_journal(f"[auto] {summary}", "observation")
        else:
            await write_journal("[auto] Heartbeat completed with no output", "observation")

        return True
    except Exception:
        logger.exception("Auto-journal failed for session %s", session_id)
        return False


def _validate_heartbeat_format(content: str) -> tuple[str, bool]:
    """Validate heartbeat output format.

    Returns (status, format_compliant):
    - HEARTBEAT_OK → ("success", True)
    - HEARTBEAT_ACTION → ("action", True)
    - Anything else → ("success", False) with a warning
    """
    if not content:
        return "success", False

    text = content.strip()
    if text.startswith("HEARTBEAT_OK"):
        return "success", True
    if text.startswith("HEARTBEAT_ACTION"):
        return "action", True

    logger.warning("Heartbeat output missing format prefix: %.60s...", text[:60])
    return "success", False


async def fallback_journal(error: str) -> None:
    """Journal an error even when the entire heartbeat completion fails."""
    try:
        from app.services.tools._executor_persona import write_journal

        await write_journal(f"[auto] Heartbeat failed: {error}", "observation")
    except Exception:
        logger.exception("Fallback journal also failed")


__all__ = [
    "fallback_journal",
    "postprocess_heartbeat",
]
