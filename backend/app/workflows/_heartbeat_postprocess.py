"""Post-heartbeat lifecycle — guaranteed summaries and format validation.

Runs after complete_internal() returns, ensuring outcomes that persona behavior
alone cannot guarantee.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.mcp_constants import build_mcp_tool_name
from app.workflows._completion_review import CompletionReviewOutcome, review_persona_completion
from app.workflows._heartbeat_recall import warm_heartbeat_recall_sections
from app.workflows._session_postprocess import (
    ensure_session_summary as _shared_ensure_session_summary,
)
from app.workflows._session_postprocess import (
    extract_synthetic_summary as _shared_extract_synthetic_summary,
)
from app.workflows._session_postprocess import (
    has_inline_summary_tag as _shared_has_inline_summary_tag,
)
from app.workflows._session_postprocess import (
    inline_summary_contract_issues as _shared_inline_summary_contract_issues,
)
from app.workflows._session_postprocess import (
    progress_tag_contract_issues as _shared_progress_tag_contract_issues,
)

if TYPE_CHECKING:
    from app.api.complete.types import CompletionInternalResult

logger = logging.getLogger(__name__)


async def log_agent_performance(*args: Any, **kwargs: Any) -> str:
    """Lazily import performance logging so tests can patch the heartbeat seam."""
    from app.services.tools._executor_performance import (
        log_agent_performance as _log_agent_performance,
    )

    return await _log_agent_performance(*args, **kwargs)


def _followup_from_completion_review(
    completion_review: CompletionReviewOutcome | None,
) -> tuple[str | None, str | None]:
    """Return (followup_reason, followup_note) derived from a completion review outcome."""
    if not (completion_review and completion_review.used):
        return None, None
    if completion_review.decision == "continue":
        return "completion_review_continue", completion_review.reason
    if completion_review.decision == "escalate":
        return "completion_review_escalate", completion_review.reason
    return None, None


def _build_heartbeat_result(
    *,
    status: str,
    result: CompletionInternalResult,
    interval_minutes: int,
    format_ok: bool,
    summary_stored: bool,
    mcp_retried: int,
    followup_dispatched: bool,
    followup_reason: str | None,
    completion_review: CompletionReviewOutcome | None,
) -> Any:
    from app.workflows.persona_heartbeat import HeartbeatResult

    return HeartbeatResult(
        status=status,
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        interval_minutes=interval_minutes,
        error=result.error,
        format_compliant=format_ok,
        summary_stored=summary_stored,
        mcp_retried=mcp_retried,
        followup_dispatched=followup_dispatched,
        followup_reason=followup_reason,
        completion_review_used=bool(completion_review and completion_review.used),
        completion_review_decision=completion_review.decision if completion_review else None,
        completion_review_reason=completion_review.reason if completion_review else None,
        completion_review_session_id=completion_review.session_id if completion_review else None,
        completion_review_agent_slug=completion_review.reviewer_agent_slug if completion_review else None,
        completion_review_model_id=completion_review.reviewer_model_id if completion_review else None,
    )


async def _record_metrics_and_retry(
    result: CompletionInternalResult,
    session_id: str,
    format_ok: bool,
    summary_stored: bool,
) -> int:
    """Record Redis metrics and retry any failed MCP tools. Returns mcp_retried count."""
    from app.workflows._heartbeat_redis import record_heartbeat_metrics

    await record_heartbeat_metrics(
        session_id=session_id,
        format_compliant=format_ok,
        summary_stored=summary_stored,
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        had_error=result.error is not None,
    )
    return await _retry_failed_mcp_tools(session_id)


async def _resolve_followup(
    content: str,
    session_id: str,
    target_project_id: str | None,
) -> tuple[str | None, str | None, CompletionReviewOutcome | None]:
    """Gather context and return (followup_reason, followup_note, completion_review)."""
    cleanup_status = await _get_cleanup_status_summary(target_project_id=target_project_id)
    workstream_inventory = await _get_workstream_inventory(target_project_id=target_project_id)
    completion_review = await _maybe_review_completion(
        content=content,
        session_id=session_id,
        target_project_id=target_project_id,
        cleanup_status=cleanup_status,
        workstream_inventory=workstream_inventory,
    )
    followup_reason = _detect_followup_reason(content, cleanup_status, workstream_inventory)
    followup_note = None
    if followup_reason is None:
        followup_reason, followup_note = _followup_from_completion_review(completion_review)
    return followup_reason, followup_note, completion_review


async def postprocess_heartbeat(
    result: CompletionInternalResult,
    interval_minutes: int,
    target_project_id: str | None = None,
):
    """Post-process heartbeat: summaries, format validation, metrics.

    Returns a HeartbeatResult instance.
    """
    content = result.content or ""
    session_id = result.session_id

    summary_stored = await _ensure_session_summary(session_id, content)
    status, format_ok, summary_tag_ok, progress_tag_ok = _validate_heartbeat_format(content)
    mcp_retried = await _record_metrics_and_retry(result, session_id, format_ok, summary_stored)
    followup_reason, followup_note, completion_review = await _resolve_followup(
        content, session_id, target_project_id
    )
    followup_dispatched = False
    if followup_reason:
        followup_dispatched = await _dispatch_followup_wake(
            followup_reason,
            target_project_id,
            note=followup_note,
            parent_session_id=session_id,
        )
    await _log_heartbeat_performance_observation(
        result=result,
        format_ok=format_ok,
        summary_tag_ok=summary_tag_ok,
        progress_tag_ok=progress_tag_ok,
        followup_reason=followup_reason,
        completion_review=completion_review,
        target_project_id=target_project_id,
    )
    await _warm_recall_cache(target_project_id)
    return _build_heartbeat_result(
        status=status,
        result=result,
        interval_minutes=interval_minutes,
        format_ok=format_ok,
        summary_stored=summary_stored,
        mcp_retried=mcp_retried,
        followup_dispatched=followup_dispatched,
        followup_reason=followup_reason,
        completion_review=completion_review,
    )


async def _warm_recall_cache(target_project_id: str | None) -> None:
    """Refresh the next-heartbeat recall cache without failing the current run."""
    try:
        await warm_heartbeat_recall_sections(target_project_id)
    except Exception:
        logger.debug("Failed to warm heartbeat recall cache", exc_info=True)


async def _ensure_session_summary(session_id: str, content: str) -> bool:
    """Ensure the session has a summary — from inline tags or synthetic fallback."""
    return await _shared_ensure_session_summary(
        session_id,
        content,
        agent_id="persona",
        empty_fallback="Heartbeat completed (no output)",
    )


def _extract_synthetic_summary(content: str) -> str:
    """Extract a synthetic summary from heartbeat output.

    Parses HEARTBEAT_OK/HEARTBEAT_ACTION prefix and extracts the sentence after it.
    Falls back to first 120 chars of content.
    """
    return _shared_extract_synthetic_summary(content)


def _build_performance_observation(
    *,
    result: CompletionInternalResult,
    format_ok: bool,
    summary_tag_ok: bool,
    progress_tag_ok: bool,
    followup_reason: str | None,
    completion_review: CompletionReviewOutcome | None,
) -> dict[str, str] | None:
    notes: list[str] = []
    if result.error:
        notes.append(f"runtime error: {result.error}")
    if "HEARTBEAT_OK" not in (result.content or "") and "HEARTBEAT_ACTION" not in (result.content or ""):
        notes.append("missing HEARTBEAT_OK/HEARTBEAT_ACTION prefix")
    elif not summary_tag_ok:
        notes.append("missing inline [[S:...]] summary tag")
    elif not progress_tag_ok:
        notes.append("missing meaningful [[P:...]] progress tags")
    if followup_reason and not followup_reason.startswith("completion_review_"):
        notes.append(f"post-run residue detected: {followup_reason}")
    if completion_review and completion_review.used and completion_review.decision in {"continue", "escalate"}:
        reason = (completion_review.reason or "no reason provided").strip()
        notes.append(
            f"completion review requested {completion_review.decision}: {reason}"
        )
    if not notes:
        return None
    return {
        "feedback_type": "friction",
        "outcome": "failure" if result.error else "partial",
        "content": "Heartbeat self-reflection signals: " + "; ".join(notes),
    }


async def _log_heartbeat_performance_observation(
    *,
    result: CompletionInternalResult,
    format_ok: bool,
    summary_tag_ok: bool,
    progress_tag_ok: bool,
    followup_reason: str | None,
    completion_review: CompletionReviewOutcome | None,
    target_project_id: str | None,
) -> None:
    observation = _build_performance_observation(
        result=result,
        format_ok=format_ok,
        summary_tag_ok=summary_tag_ok,
        progress_tag_ok=progress_tag_ok,
        followup_reason=followup_reason,
        completion_review=completion_review,
    )
    if observation is None:
        return

    try:
        await log_agent_performance(
            agent_slug="persona",
            model_id=result.model_used or result.model,
            feedback_type=observation["feedback_type"],
            content=observation["content"],
            outcome=observation["outcome"],
            task_type="heartbeat",
            project_id=target_project_id or "persona-sandbox",
            session_id=result.session_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            tool_calls_count=result.tool_calls_count,
            turns=result.turns,
            logged_by="system",
        )
    except Exception:
        logger.debug("Failed to log heartbeat performance observation", exc_info=True)



def _has_inline_summary_tag(content: str | None) -> bool:
    """Return True when heartbeat output contains an inline [[S:...]] tag."""
    return _shared_has_inline_summary_tag(content)


def _inline_summary_contract_issues(content: str | None) -> list[str]:
    """Return heartbeat summary-tag contract issues."""
    return _shared_inline_summary_contract_issues(content)


def _progress_tag_contract_issues(content: str | None) -> list[str]:
    """Return heartbeat progress-tag contract issues."""
    return _shared_progress_tag_contract_issues(content, require_progress=True)


def _validate_heartbeat_format(content: str) -> tuple[str, bool, bool, bool]:
    """Validate heartbeat output contract.

    Returns (status, format_compliant, summary_tag_ok, progress_tag_ok).
    Compliance requires a HEARTBEAT_OK/HEARTBEAT_ACTION prefix, meaningful
    inline [[P:...]] progress tags, and an inline [[S:...]] summary tag.
    """
    if not content:
        return "success", False, False, False

    # Multi-turn heartbeats place the prefix in the final message,
    # not at the start of the concatenated content.
    status = "success"
    prefix_ok = False
    if "HEARTBEAT_OK" in content:
        prefix_ok = True
    elif "HEARTBEAT_ACTION" in content:
        status = "action"
        prefix_ok = True
    else:
        logger.warning("Heartbeat output missing format prefix: %.60s...", content.strip()[:60])

    summary_issues = _inline_summary_contract_issues(content)
    summary_tag_ok = not summary_issues
    progress_issues = _progress_tag_contract_issues(content)
    progress_tag_ok = not progress_issues
    if prefix_ok and summary_issues:
        logger.warning(
            "Heartbeat summary contract issues: %s | %.60s...",
            "; ".join(summary_issues),
            content.strip()[:60],
        )
    if prefix_ok and progress_issues:
        logger.warning(
            "Heartbeat progress contract issues: %s | %.60s...",
            "; ".join(progress_issues),
            content.strip()[:60],
        )

    return status, prefix_ok and summary_tag_ok and progress_tag_ok, summary_tag_ok, progress_tag_ok


async def _get_cleanup_status_summary(target_project_id: str | None = None) -> str:
    from app.workflows._heartbeat_data import (
        _get_cleanup_status_summary as fetch_cleanup_status,
    )
    from app.workflows._heartbeat_data import (
        _query_recent_workstream_sessions,
    )

    workstream_rows = await _query_recent_workstream_sessions(target_project_id)
    return await fetch_cleanup_status(target_project_id, workstream_rows=workstream_rows)


async def _get_workstream_inventory(target_project_id: str | None = None) -> str:
    from app.workflows._heartbeat_data import (
        _get_workstream_inventory as fetch_workstream_inventory,
    )

    return await fetch_workstream_inventory(target_project_id=target_project_id)


def _detect_followup_reason(
    content: str,
    cleanup_status: str,
    workstream_inventory: str,
) -> str | None:
    if "HEARTBEAT_OK" not in (content or ""):
        return None
    if "ACTIONABLE-CLEANUP[" in cleanup_status:
        return "cleanup_actionable"
    if "state=stale_running_task" in workstream_inventory:
        return "stale_running_task"
    if "state=completed_ready_for_closure" in workstream_inventory:
        return "completed_ready_for_closure"
    return None


async def _maybe_review_completion(
    *,
    content: str,
    session_id: str,
    target_project_id: str | None,
    cleanup_status: str,
    workstream_inventory: str,
) -> CompletionReviewOutcome | None:
    if "HEARTBEAT_OK" not in (content or ""):
        return None
    if _detect_followup_reason(content, cleanup_status, workstream_inventory):
        return None
    return await review_persona_completion(
        project_id=target_project_id or "persona-sandbox",
        completion_content=content,
        cleanup_status=cleanup_status,
        workstream_inventory=workstream_inventory,
        parent_session_id=session_id,
    )


def _build_followup_prompt(reason: str, note: str | None = None) -> str:
    detail = f"\nReviewer note: {note}\n" if note else "\n"
    return (
        "The previous heartbeat ended with HEARTBEAT_OK, but a post-run check still showed "
        f"obvious unresolved canonical residue: {reason}.{detail}\n"
        "Re-check only that residue chain and do the concrete next step if it is still valid. "
        "If it is no longer actionable, say why. Do not start speculative new work, model review, "
        "or broad exploration."
    )


async def _dispatch_followup_wake(
    reason: str,
    target_project_id: str | None = None,
    *,
    note: str | None = None,
    parent_session_id: str | None = None,
) -> bool:
    from app.db import async_session
    from app.workflows.persona_heartbeat import HEARTBEAT_PROJECT, _resolve_persona
    from app.workflows.persona_wake import dispatch_wake

    async with async_session() as db:
        model, provider, temperature, thinking_level, _, _ = await _resolve_persona(
            db,
            project_id=target_project_id or HEARTBEAT_PROJECT,
        )

    dispatch_wake(
        agent_slug="persona",
        model=model,
        provider=provider,
        temperature=temperature,
        prompt=_build_followup_prompt(reason, note=note),
        project_id=target_project_id or HEARTBEAT_PROJECT,
        event_type="heartbeat_completion_review" if reason.startswith("completion_review_") else "heartbeat_followup",
        thinking_level=thinking_level,
        parent_session_id=parent_session_id,
    )
    return True


# Tools that can be safely retried by calling the Python function directly.
# Keys are MCP tool names as stored in session_events.
_RETRYABLE_TOOLS: set[str] = {
    build_mcp_tool_name("log_agent_performance"),
    build_mcp_tool_name("dispatch_agent"),
}


async def _query_stream_closed_failures(session_id: str) -> list:
    """Query session_events for tool_result rows that failed with 'Stream closed'."""
    from sqlalchemy import text

    from app.db import async_session

    async with async_session() as db:
        result = await db.execute(
            text(
                "SELECT se.tool_name, se.sequence FROM session_events se"
                " WHERE se.session_id = :sid AND se.event_type = 'tool_result'"
                " AND (se.tool_output->>'content' = 'Stream closed'"
                "  OR se.content = 'Stream closed')"
                " ORDER BY se.sequence"
            ),
            {"sid": session_id},
        )
        return list(result.fetchall())


async def _fetch_tool_args(session_id: str, tool_name: str, seq: int) -> dict | None:
    """Return the tool_input dict for the tool_use event that preceded *seq*, or None."""
    import json

    from sqlalchemy import text

    from app.db import async_session

    async with async_session() as db:
        use_result = await db.execute(
            text(
                "SELECT tool_input FROM session_events"
                " WHERE session_id = :sid AND event_type = 'tool_use'"
                " AND tool_name = :tool AND sequence < :seq"
                " ORDER BY sequence DESC LIMIT 1"
            ),
            {"sid": session_id, "tool": tool_name, "seq": seq},
        )
        row = use_result.fetchone()

    if not row or not row.tool_input:
        logger.warning("No tool_use args found for %s retry (session=%s)", tool_name, session_id)
        return None

    return row.tool_input if isinstance(row.tool_input, dict) else json.loads(row.tool_input)


async def _execute_tool_retry(tool_name: str, tool_args: dict) -> None:
    """Call the Python function that backs *tool_name* with *tool_args*."""
    if tool_name == build_mcp_tool_name("log_agent_performance"):
        from app.services.tools._executor_performance import log_agent_performance

        await log_agent_performance(**tool_args)
    elif tool_name == build_mcp_tool_name("dispatch_agent"):
        from app.services.tools._executor_consultation import dispatch_agent

        await dispatch_agent(
            project_id=tool_args.get("project_id"),
            agent_slug=tool_args.get("agent_slug", ""),
            task=tool_args.get("task", ""),
            max_turns=tool_args.get("max_turns"),
        )


async def _retry_single_tool(session_id: str, tool_name: str, seq: int) -> bool:
    """Retry one failed MCP tool call. Returns True on success."""
    if tool_name not in _RETRYABLE_TOOLS:
        logger.warning(
            "MCP 'Stream closed' for non-retryable tool %s (session=%s, seq=%d)",
            tool_name, session_id, seq,
        )
        return False

    tool_args = await _fetch_tool_args(session_id, tool_name, seq)
    if tool_args is None:
        return False

    try:
        await _execute_tool_retry(tool_name, tool_args)
        logger.info("MCP retry succeeded: %s (session=%s)", tool_name, session_id)
        return True
    except Exception:
        logger.exception("MCP retry failed: %s (session=%s)", tool_name, session_id)
        return False


async def _retry_failed_mcp_tools(session_id: str) -> int:
    """Retry MCP tools that failed with 'Stream closed'. Returns count retried."""
    try:
        failures = await _query_stream_closed_failures(session_id)
        if not failures:
            return 0
        results = [await _retry_single_tool(session_id, tool_name, seq) for tool_name, seq in failures]
        return sum(results)
    except Exception:
        logger.exception("_retry_failed_mcp_tools failed for session %s", session_id)
        return 0


__all__ = [
    "postprocess_heartbeat",
]
