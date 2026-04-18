"""Session analysis: citation scanning and task outcome processing."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select

from app.db import _get_session_factory
from app.models import Session

from .citation_parser import (
    extract_feedback_tag_strings,
    extract_summary_tag_strings,
    extract_uuid_prefixes,
    resolve_full_uuids,
)
from .metrics_collector import update_citation_metrics
from .session_analysis_feedback import fetch_feedback_tag_dicts, persist_feedback_items
from .session_analysis_summary import build_git_digest
from .session_queries import (
    extract_citations_from_events,
    extract_summary_tags_from_events,
    find_sessions_by_task,
    get_cited_memories,
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


@dataclass(frozen=True)
class _TranscriptArtifacts:
    citation_prefixes: list[str]
    feedback_tags: list[str]
    summary_tags: list[str]


@dataclass(frozen=True)
class _SummaryContext:
    transcript_path: str | None
    git_context: str | None
    branch: str | None


async def _load_summary_context(session_id: str) -> _SummaryContext | None:
    """Load persisted summary context for replay analysis."""
    try:
        async with _get_session_factory()() as db:
            row = await db.execute(select(Session.provider_metadata).where(Session.id == session_id))
            provider_metadata = row.scalar_one_or_none()
    except Exception as e:
        logger.debug("Summary context lookup skipped for %s: %s", session_id, e)
        return None
    if not isinstance(provider_metadata, dict):
        return None
    summary_context = provider_metadata.get("summary_context")
    if not isinstance(summary_context, dict):
        return None
    return _SummaryContext(
        transcript_path=summary_context.get("transcript_path"),
        git_context=summary_context.get("git_context"),
        branch=summary_context.get("branch"),
    )


def _load_transcript_artifacts(transcript_path: str | None) -> _TranscriptArtifacts | None:
    """Load inline citations, feedback, and summaries from a transcript file."""
    if not transcript_path:
        return None
    from .summary_transcript import read_transcript_text
    transcript_text = read_transcript_text(transcript_path)
    if not transcript_text:
        return _TranscriptArtifacts(citation_prefixes=[], feedback_tags=[], summary_tags=[])
    return _TranscriptArtifacts(
        citation_prefixes=extract_uuid_prefixes(transcript_text),
        feedback_tags=extract_feedback_tag_strings(transcript_text),
        summary_tags=extract_summary_tag_strings(transcript_text),
    )


async def _resolve_prefixes(
    session_id: str,
    citation_prefixes: list[str] | None,
    artifacts: _TranscriptArtifacts | None,
) -> list[str]:
    """Return normalized 8-char citation prefixes from args, transcript, or events."""
    if citation_prefixes is not None:
        return [p.lower()[:8] for p in citation_prefixes if len(p) >= 8]
    if artifacts is not None:
        return artifacts.citation_prefixes
    return await extract_citations_from_events(session_id)


async def _credit_citations(session_id: str, resolved_uuids: list[str]) -> int:
    """Track and audit newly credited memory citations for a session."""
    if not resolved_uuids:
        return 0
    existing_uuids = set(await get_cited_memories(session_id))
    new_uuids = [uuid for uuid in resolved_uuids if uuid not in existing_uuids]
    if new_uuids:
        await track_referenced_batch(new_uuids)
        for uuid in new_uuids:
            track_helpful(uuid)
        await store_cite_event(session_id, new_uuids)
    all_cited_uuids = list(dict.fromkeys([*sorted(existing_uuids), *resolved_uuids]))
    await update_citation_metrics(session_id=session_id, memories_cited=all_cited_uuids)
    return len(new_uuids)


async def _process_feedback_tags(
    session_id: str,
    feedback_tags: list[str] | None = None,
) -> int:
    """Process feedback tags from CC transcript or session events."""
    tag_dicts = await fetch_feedback_tag_dicts(session_id, feedback_tags)
    if not tag_dicts:
        return 0
    async with _get_session_factory()() as db:
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
        git_digest=build_git_digest(git_context),
    )
    logger.info("Stored inline summary for session %s: outcome=%s", session_id, tag.outcome)
    return True


def _apply_summary_context(
    ctx: _SummaryContext,
    transcript_path: str | None,
    git_context: str | None,
    branch: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Override analysis params with stored context values where unset."""
    return (
        transcript_path if transcript_path is not None else ctx.transcript_path,
        git_context if git_context is not None else ctx.git_context,
        branch if branch is not None else ctx.branch,
    )


async def _process_session_tags(
    session_id: str,
    artifacts: _TranscriptArtifacts | None,
    feedback_tags: list[str] | None,
    summary_tags: list[str] | None,
    git_context: str | None,
    branch: str | None,
) -> tuple[int, bool]:
    """Run feedback and summary tag processing; return (feedback_created, summary_stored)."""
    effective_feedback = feedback_tags if feedback_tags is not None else (
        artifacts.feedback_tags if artifacts is not None else None
    )
    effective_summary = summary_tags if summary_tags is not None else (
        artifacts.summary_tags if artifacts is not None else await extract_summary_tags_from_events(session_id)
    )
    feedback_created = await _process_feedback_tags(session_id, effective_feedback)
    summary_stored = await _process_summary_tags(session_id, effective_summary, git_context, branch)
    return feedback_created, summary_stored


async def analyze_session(
    session_id: str,
    citation_prefixes: list[str] | None = None,
    feedback_tags: list[str] | None = None,
    summary_tags: list[str] | None = None,
    git_context: str | None = None,
    branch: str | None = None,
    transcript_path: str | None = None,
) -> AnalysisResult:
    """Analyze a session for memory citations and credit them."""
    ctx = await _load_summary_context(session_id)
    if ctx is not None:
        transcript_path, git_context, branch = _apply_summary_context(
            ctx, transcript_path, git_context, branch
        )

    artifacts = _load_transcript_artifacts(transcript_path)
    prefixes = await _resolve_prefixes(session_id, citation_prefixes, artifacts)
    feedback_created, summary_stored = await _process_session_tags(
        session_id, artifacts, feedback_tags, summary_tags, git_context, branch,
    )

    if not prefixes:
        return AnalysisResult(
            session_id=session_id, citations_found=0, citations_credited=0,
            feedback_created=feedback_created, summary_stored=summary_stored,
        )

    group_id = await get_session_group_id(session_id)
    resolved_uuids = list((await resolve_full_uuids(prefixes, group_id=group_id)).values())
    citations_credited = await _credit_citations(session_id, resolved_uuids)
    logger.info(
        "Session %s: found %d citation prefixes, credited %d, feedback %d, summary %s",
        session_id, len(prefixes), citations_credited, feedback_created, summary_stored,
    )
    return AnalysisResult(
        session_id=session_id,
        citations_found=len(prefixes),
        citations_credited=citations_credited,
        feedback_created=feedback_created,
        summary_stored=summary_stored,
    )


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
