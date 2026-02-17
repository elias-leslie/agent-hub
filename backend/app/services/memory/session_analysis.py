"""Session analysis for memory citation scanning and task outcome processing.

Provides two core functions:
1. analyze_session() - Extract and credit citations from CC transcripts or API sessions
2. process_task_outcome() - Propagate task success/failure to memory scoring
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .citation_parser import resolve_full_uuids
from .metrics_collector import update_citation_metrics
from .session_queries import (
    extract_citations_from_events,
    find_sessions_by_task,
    get_memories_loaded,
    get_session_group_id,
    store_cite_event,
)
from .usage_tracker import track_referenced_batch, track_success_batch

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Result of session citation analysis."""

    session_id: str
    citations_found: int
    citations_credited: int


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
) -> AnalysisResult:
    """Analyze a session for memory citations and credit them.

    Two paths:
    1. CC path: citation_prefixes provided directly (from Stop.sh transcript grep)
    2. API path: query session_events for assistant_message events, extract citations

    Args:
        session_id: Session to analyze
        citation_prefixes: Pre-extracted 8-char UUID prefixes (CC path)

    Returns:
        AnalysisResult with citation counts
    """
    prefixes: list[str] = []

    if citation_prefixes is not None:
        # CC path: use provided prefixes directly
        prefixes = [p.lower()[:8] for p in citation_prefixes if len(p) >= 8]
    else:
        # API path: scan session_events for citations
        prefixes = await extract_citations_from_events(session_id)

    if not prefixes:
        return AnalysisResult(
            session_id=session_id,
            citations_found=0,
            citations_credited=0,
        )

    # Determine group_id from session's project
    group_id = await get_session_group_id(session_id)

    # Resolve 8-char prefixes to full UUIDs
    prefix_to_uuid = await resolve_full_uuids(prefixes, group_id=group_id)
    resolved_uuids = list(prefix_to_uuid.values())

    if resolved_uuids:
        # Credit via usage tracker (citation = referenced, not helpful)
        await track_referenced_batch(resolved_uuids)

        # Store audit trail via event storage
        await store_cite_event(session_id, resolved_uuids)

        # Update citation metrics on injection record
        await update_citation_metrics(
            session_id=session_id,
            memories_cited=resolved_uuids,
        )

    logger.info(
        "Session %s: found %d citation prefixes, credited %d",
        session_id,
        len(prefixes),
        len(resolved_uuids),
    )

    return AnalysisResult(
        session_id=session_id,
        citations_found=len(prefixes),
        citations_credited=len(resolved_uuids),
    )


async def process_task_outcome(
    session_id: str,
    succeeded: bool,
    task_id: str | None = None,
) -> TaskOutcomeResult:
    """Process task outcome and credit loaded memories on success.

    Updates MemoryInjectionMetric.task_succeeded and credits memories on success.
    """
    # Update task_succeeded on injection metrics
    metrics_updated = await update_citation_metrics(
        session_id=session_id,
        task_succeeded=succeeded,
    )

    memories_credited = 0

    if succeeded:
        # Query memories_loaded from injection metrics for this session
        loaded_uuids = await get_memories_loaded(session_id)

        if loaded_uuids:
            await track_success_batch(loaded_uuids)
            memories_credited = len(loaded_uuids)

    logger.info(
        "Task outcome for session %s: succeeded=%s, metrics_updated=%d, memories_credited=%d",
        session_id,
        succeeded,
        metrics_updated,
        memories_credited,
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
