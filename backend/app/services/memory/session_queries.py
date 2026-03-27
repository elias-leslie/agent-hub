"""Database query helpers for session analysis.

Internal module providing database queries for session citation analysis.
Not intended for direct external use.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import _get_session_factory
from app.models import MemoryInjectionMetric, Session, SessionEvent
from app.services._session_metadata_helpers import metadata_paths
from app.services.ownership_lanes import infer_task_id

from .citation_parser import (
    extract_feedback_tags,
    extract_summary_tag_strings,
    extract_uuid_prefixes,
)
from .memory_utils import build_group_id
from .service import MemoryScope

logger = logging.getLogger(__name__)
_TASK_SESSION_LOOKBACK_DAYS = 7


def _session_matches_task(session: Session, task_id: str) -> bool:
    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    return infer_task_id(session.external_id, session.current_branch, *metadata_paths(metadata)) == task_id


async def extract_citations_from_events(session_id: str) -> list[str]:
    """Extract citation UUID prefixes from session_events assistant messages."""
    session_factory = _get_session_factory()

    async with session_factory() as db:
        query = (
            select(SessionEvent.content)
            .where(SessionEvent.session_id == session_id)
            .where(SessionEvent.event_type == "assistant_message")
        )
        result = await db.execute(query)
        rows = result.scalars().all()

    all_prefixes: set[str] = set()
    for content in rows:
        if content:
            prefixes = extract_uuid_prefixes(content)
            all_prefixes.update(prefixes)

    return list(all_prefixes)


async def extract_feedback_from_events(session_id: str) -> list[dict]:
    """Extract inline feedback tags from session_events assistant messages.

    Returns list of dicts with feedback_type, component_id, description.
    """
    session_factory = _get_session_factory()

    async with session_factory() as db:
        query = (
            select(SessionEvent.content)
            .where(SessionEvent.session_id == session_id)
            .where(SessionEvent.event_type == "assistant_message")
        )
        result = await db.execute(query)
        rows = result.scalars().all()

    all_tags: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for content in rows:
        if content:
            tags = extract_feedback_tags(content)
            for tag in tags:
                key = (tag.component_id, tag.feedback_type)
                if key not in seen:
                    all_tags.append(tag.model_dump())
                    seen.add(key)

    return all_tags


async def extract_summary_tags_from_events(session_id: str) -> list[str]:
    """Extract inline summary tag strings from session_events assistant messages."""
    session_factory = _get_session_factory()

    try:
        async with session_factory() as db:
            query = (
                select(SessionEvent.content)
                .where(SessionEvent.session_id == session_id)
                .where(SessionEvent.event_type == "assistant_message")
            )
            result = await db.execute(query)
            rows = result.scalars().all()
    except Exception as e:
        logger.debug("Could not load summary tags for session %s: %s", session_id, e)
        return []

    tags: list[str] = []
    seen: set[str] = set()
    for content in rows:
        if not content:
            continue
        for tag in extract_summary_tag_strings(content):
            if tag not in seen:
                tags.append(tag)
                seen.add(tag)
    return tags


async def get_session_group_id(session_id: str) -> str:
    """Get the group_id for a session based on its project_id."""
    session_factory = _get_session_factory()

    async with session_factory() as db:
        query = select(Session.project_id).where(Session.id == session_id)
        result = await db.execute(query)
        project_id = result.scalar_one_or_none()

    if project_id:
        return build_group_id(MemoryScope.PROJECT, project_id)
    return "global"


async def get_memories_loaded(session_id: str) -> list[str]:
    """Get all memory UUIDs loaded for a session from injection metrics."""
    session_factory = _get_session_factory()

    async with session_factory() as db:
        query = (
            select(MemoryInjectionMetric.memories_loaded)
            .where(MemoryInjectionMetric.session_id == session_id)
            .where(MemoryInjectionMetric.memories_loaded.isnot(None))
        )
        result = await db.execute(query)
        rows = result.scalars().all()

    # Flatten all loaded UUIDs across multiple injection records, deduplicate
    all_uuids: set[str] = set()
    for loaded in rows:
        if loaded:
            all_uuids.update(loaded)

    return list(all_uuids)


async def store_cite_event(session_id: str, cited_uuids: list[str]) -> None:
    """Store a memory citation event for audit trail."""
    from app.services.event_storage import store_memory_cite_event

    session_factory = _get_session_factory()

    try:
        async with session_factory() as db:
            await store_memory_cite_event(db, session_id, cited_uuids)
            await db.commit()
    except Exception as e:
        logger.warning("Failed to store cite event for session %s: %s", session_id, e)


async def get_cited_memories(session_id: str) -> list[str]:
    """Return unique memory UUIDs already credited for a session."""
    session_factory = _get_session_factory()

    try:
        async with session_factory() as db:
            query = (
                select(SessionEvent.tool_input)
                .where(SessionEvent.session_id == session_id)
                .where(SessionEvent.event_type == "memory_cite")
            )
            result = await db.execute(query)
            rows = result.scalars().all()
    except Exception as e:
        logger.debug("Could not load cited memories for session %s: %s", session_id, e)
        return []

    cited: set[str] = set()
    for tool_input in rows:
        if not isinstance(tool_input, dict):
            continue
        uuids = tool_input.get("uuids")
        if not isinstance(uuids, list):
            continue
        cited.update(str(uuid) for uuid in uuids if isinstance(uuid, str))

    return list(cited)


async def find_sessions_by_task(
    task_id: str,
    project_id: str | None = None,
    started_at: str | None = None,
) -> list[str]:
    """Find session IDs associated with a task via injection metrics.

    Primary lookup: MemoryInjectionMetric.external_id matching task_id.
    Fallback: When external_id not set, find sessions by project_id + time range.

    Args:
        task_id: SummitFlow task ID
        project_id: Project ID for fallback lookup
        started_at: ISO timestamp of task start for time-bounded fallback

    Returns:
        List of unique session IDs
    """
    session_factory = _get_session_factory()

    async with session_factory() as db:
        # Primary: lookup by external_id
        query = (
            select(MemoryInjectionMetric.session_id)
            .where(MemoryInjectionMetric.external_id == task_id)
            .where(MemoryInjectionMetric.session_id.isnot(None))
            .distinct()
        )
        result = await db.execute(query)
        session_ids = [sid for sid in result.scalars().all() if sid is not None]

        if session_ids:
            return session_ids

        # Fallback: inspect task-linked sessions directly within the task's project/time window.
        if project_id and started_at:
            try:
                start_dt = datetime.fromisoformat(started_at)
            except ValueError:
                logger.warning("Invalid started_at format: %s", started_at)
                return session_ids
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=UTC)

            session_query = (
                select(Session)
                .where(Session.project_id == project_id)
                .where(Session.created_at >= start_dt)
                .where(Session.created_at >= datetime.now(UTC) - timedelta(days=_TASK_SESSION_LOOKBACK_DAYS))
                .where(Session.session_type.in_(("agent", "claude_code")))
                .order_by(Session.created_at.desc())
                .limit(200)
            )
            result = await db.execute(session_query)
            sessions = result.scalars().all()
            session_ids = list(dict.fromkeys(
                session.id for session in sessions if _session_matches_task(session, task_id)
            ))

            if session_ids:
                logger.info(
                    "Task %s: found %d sessions via session lane fallback (project=%s, since=%s)",
                    task_id,
                    len(session_ids),
                    project_id,
                    started_at,
                )
                return session_ids

            # Final fallback: lookup by memory injection metrics within the task time window.
            fallback_query = (
                select(MemoryInjectionMetric.session_id)
                .where(MemoryInjectionMetric.project_id == project_id)
                .where(MemoryInjectionMetric.session_id.isnot(None))
                .where(MemoryInjectionMetric.task_succeeded.is_(None))
                .where(MemoryInjectionMetric.created_at >= start_dt)
                .distinct()
            )
            result = await db.execute(fallback_query)
            session_ids = [sid for sid in result.scalars().all() if sid is not None]

            if session_ids:
                logger.info(
                    "Task %s: found %d sessions via project fallback (project=%s, since=%s)",
                    task_id,
                    len(session_ids),
                    project_id,
                    started_at,
                )

        return session_ids
