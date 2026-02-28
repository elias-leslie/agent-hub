"""Session analysis: citation scanning and task outcome processing."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select

from .citation_parser import resolve_full_uuids
from .metrics_collector import update_citation_metrics
from .session_analysis_feedback import fetch_feedback_tag_dicts, persist_feedback_items
from .session_analysis_summary import build_git_digest
from .session_queries import (
    extract_citations_from_events,
    find_sessions_by_task,
    get_memories_loaded,
    get_session_group_id,
    store_cite_event,
)
from .usage_tracker import track_helpful, track_referenced_batch, track_success_batch

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Result of session citation analysis."""

    session_id: str
    citations_found: int
    citations_credited: int
    feedback_created: int = 0
    summary_stored: bool = False


@dataclass
class TaskOutcomeResult:
    """Result of task outcome processing."""

    session_id: str
    task_succeeded: bool
    metrics_updated: int
    memories_credited: int


async def analyze_session(
    session_id: str,
    citation_prefixes: list[str] | None = None,
    feedback_tags: list[str] | None = None,
    summary_tags: list[str] | None = None,
    git_context: str | None = None,
    branch: str | None = None,
    is_worktree: bool = False,
) -> AnalysisResult:
    """Analyze a session for memory citations and credit them."""
    if citation_prefixes is not None:
        prefixes = [p.lower()[:8] for p in citation_prefixes if len(p) >= 8]
    else:
        prefixes = await extract_citations_from_events(session_id)

    feedback_created = await _process_feedback_tags(session_id, feedback_tags)
    summary_stored = await _process_summary_tags(
        session_id, summary_tags, git_context, branch, is_worktree,
    )

    if not prefixes:
        return AnalysisResult(
            session_id=session_id,
            citations_found=0,
            citations_credited=0,
            feedback_created=feedback_created,
            summary_stored=summary_stored,
        )

    group_id = await get_session_group_id(session_id)
    prefix_to_uuid = await resolve_full_uuids(prefixes, group_id=group_id)
    resolved_uuids = list(prefix_to_uuid.values())
    await _credit_citations(session_id, resolved_uuids)
    logger.info(
        "Session %s: found %d citation prefixes, credited %d, feedback %d, summary %s",
        session_id, len(prefixes), len(resolved_uuids), feedback_created, summary_stored,
    )
    return AnalysisResult(
        session_id=session_id,
        citations_found=len(prefixes),
        citations_credited=len(resolved_uuids),
        feedback_created=feedback_created,
        summary_stored=summary_stored,
    )


async def _credit_citations(session_id: str, resolved_uuids: list[str]) -> None:
    """Track and audit credited memory citations."""
    if not resolved_uuids:
        return
    await track_referenced_batch(resolved_uuids)
    for uuid in resolved_uuids:
        track_helpful(uuid)
    await store_cite_event(session_id, resolved_uuids)
    await update_citation_metrics(session_id=session_id, memories_cited=resolved_uuids)


async def _process_feedback_tags(
    session_id: str,
    feedback_tags: list[str] | None = None,
) -> int:
    """Process feedback tags from CC transcript or session events."""
    from app.db import _get_session_factory
    from app.models import Session
    tag_dicts = await fetch_feedback_tag_dicts(session_id, feedback_tags)
    if not tag_dicts:
        return 0

    session_factory = _get_session_factory()
    async with session_factory() as db:
        row = await db.execute(
            select(Session.project_id, Session.agent_slug).where(Session.id == session_id)
        )
        session_info = row.one_or_none()
        if not session_info:
            logger.warning("Session %s not found for feedback processing", session_id)
            return 0
        return await persist_feedback_items(
            db, session_id, tag_dicts, session_info.project_id, session_info.agent_slug,
        )


async def _process_summary_tags(
    session_id: str,
    summary_tags: list[str] | None = None,
    git_context: str | None = None,
    branch: str | None = None,
    is_worktree: bool = False,
) -> bool:
    """Process summary tags from CC transcript. Returns True if a summary was stored."""
    if not summary_tags:
        return False

    from .citation_parser import parse_summary_tags as _parse_summary_tags
    from .summary_generator import _enforce_oneliner, _store_summary_on_session
    all_tags = [t for raw in summary_tags if isinstance(raw, str) for t in _parse_summary_tags(raw).tags]
    if not all_tags:
        return False
    tag = all_tags[-1]
    await _store_summary_on_session(
        session_id=session_id,
        summary_oneliner=_enforce_oneliner(tag.description),
        outcome=tag.outcome,
        files_touched=[],
        branch=branch,
        is_worktree=is_worktree,
        git_digest=build_git_digest(git_context),
    )

    logger.info("Stored inline summary for session %s: outcome=%s", session_id, tag.outcome)
    return True


async def process_task_outcome(
    session_id: str,
    succeeded: bool,
    task_id: str | None = None,
) -> TaskOutcomeResult:
    """Process task outcome and credit loaded memories on success."""
    metrics_updated = await update_citation_metrics(
        session_id=session_id,
        task_succeeded=succeeded,
    )
    memories_credited = 0
    if succeeded:
        loaded_uuids = await get_memories_loaded(session_id)
        if loaded_uuids:
            await track_success_batch(loaded_uuids)
            memories_credited = len(loaded_uuids)
    logger.info(
        "Task outcome for session %s: succeeded=%s, metrics_updated=%d, memories_credited=%d",
        session_id, succeeded, metrics_updated, memories_credited,
    )
    return TaskOutcomeResult(
        session_id=session_id,
        task_succeeded=succeeded,
        metrics_updated=metrics_updated,
        memories_credited=memories_credited,
    )


async def find_sessions_for_task(
    task_id: str,
    project_id: str | None = None,
    started_at: str | None = None,
) -> list[str]:
    """Find session IDs associated with a task via injection metrics."""
    return await find_sessions_by_task(task_id, project_id, started_at)
