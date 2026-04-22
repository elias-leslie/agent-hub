"""Session CRUD operations - business logic for session lifecycle."""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.agent_routing import resolve_agent
from app.services.events import publish_session_start
from app.services.session_live_activity import mark_session_completed

logger = logging.getLogger(__name__)


async def _validate_project_id(project_id: str) -> None:
    """Validate project_id against known projects, refreshing cache if stale.

    Args:
        project_id: Project identifier to validate

    Raises:
        ValueError: If project_id is not in VALID_PROJECT_IDS
    """
    from app.constants import VALID_PROJECT_IDS
    from app.constants.projects import is_cache_stale, refresh_project_ids_cache

    # Refresh project cache if stale (5-min TTL)
    if is_cache_stale():
        await refresh_project_ids_cache()

    if project_id not in VALID_PROJECT_IDS:
        raise ValueError(
            f"Unknown project_id '{project_id}'. "
            f"Valid projects: {sorted(VALID_PROJECT_IDS)}"
        )


async def _resolve_provider_and_model(
    db: AsyncSession,
    agent_slug: str | None,
    provider: str,
    model: str,
) -> tuple[str, str]:
    """Resolve provider and model, optionally overriding from agent configuration.

    Args:
        db: Database session
        agent_slug: Optional agent slug to resolve
        provider: Default provider name
        model: Default model identifier

    Returns:
        Tuple of (resolved_provider, resolved_model)
    """
    if agent_slug:
        resolved = await resolve_agent(agent_slug, db)
        return resolved.provider, resolved.model
    return provider, model


async def _build_and_persist_session(
    db: AsyncSession,
    session_id: str,
    project_id: str,
    provider: str,
    model: str,
    session_type: str,
    agent_slug: str | None,
) -> Session:
    """Create, persist, and return a new session record.

    Args:
        db: Database session
        session_id: Session identifier
        project_id: Project identifier
        provider: Provider name
        model: Model identifier
        session_type: Session type
        agent_slug: Optional agent slug

    Returns:
        Persisted session object
    """
    session = Session(
        id=session_id,
        project_id=project_id,
        provider=provider,
        model=model,
        status="active",
        session_type=session_type,
        agent_slug=agent_slug,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def create_new_session(
    db: AsyncSession,
    session_id: str | None,
    project_id: str,
    provider: str,
    model: str,
    session_type: str,
    agent_slug: str | None = None,
) -> Session:
    """Create a new session with resolved agent configuration.

    Args:
        db: Database session
        session_id: Optional custom session ID
        project_id: Project identifier
        provider: Provider name
        model: Model identifier
        session_type: Session type
        agent_slug: Optional agent slug to resolve

    Returns:
        Created session object

    Raises:
        ValueError: If project_id is not in VALID_PROJECT_IDS
    """
    await _validate_project_id(project_id)

    final_session_id = session_id or str(uuid.uuid4())
    final_provider, final_model = await _resolve_provider_and_model(
        db, agent_slug, provider, model
    )

    session = await _build_and_persist_session(
        db, final_session_id, project_id, final_provider, final_model, session_type, agent_slug
    )

    await publish_session_start(final_session_id, final_model, project_id)

    return session


async def close_session_if_active(db: AsyncSession, session: Session) -> tuple[str, str]:
    """Close a session if it's active.

    Args:
        db: Database session
        session: Session to close

    Returns:
        Tuple of (status, message)
    """
    if session.status == "completed":
        return "completed", "Session was already completed"

    mark_session_completed(
        session,
        summary="Session closed",
        termination_reason="session_closed_helper",
    )
    await db.commit()

    # Inline summary tags ([[S:outcome:description]]) are the sole summary mechanism.
    # CC sessions: Stop hook → /analyze stores tags.
    # API sessions: citation_tracker.track_inline_summaries() stores tags during streaming.
    # No async summarizer dispatch — removed Feb 2026.

    return "completed", "Session closed successfully"


async def promote_session_branch(
    db: AsyncSession,
    session: Session,
    discard_siblings: bool = False,
) -> tuple[list[str], int]:
    """Promote a session branch and optionally discard siblings.

    Args:
        db: Database session
        session: Session to promote
        discard_siblings: Whether to discard sibling sessions

    Returns:
        Tuple of (discarded_sibling_ids, patches_applied_count)
    """
    from app.services.session_branching import discard_sibling_sessions

    discarded_siblings: list[str] = []
    if discard_siblings and session.parent_session_id:
        discarded_siblings = await discard_sibling_sessions(
            db, session.parent_session_id, session.id
        )

    session.branch_status = "promoted"
    session.manual_outcome = "selected"

    patches_applied = 0
    if session.pending_patches:
        patches_applied = len(session.pending_patches)
        session.pending_patches = None

    await db.commit()

    return discarded_siblings, patches_applied


async def get_or_create_session(
    db: AsyncSession, session_id: str | None
) -> tuple[Session | None, bool]:
    """Get existing session by ID if it exists.

    Args:
        db: Database session
        session_id: Optional session ID to look up

    Returns:
        Tuple of (existing_session, is_existing) - (None, False) if not found
    """
    if not session_id:
        return None, False

    result = await db.execute(select(Session).where(Session.id == session_id))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, True

    return None, False


async def _fetch_filtered_sessions(
    db: AsyncSession,
    project_id: str | None,
    status: str | None,
    agent_slug: str | None,
    session_type: str | None,
    page: int,
    page_size: int,
    parent_session_id: str | None,
    external_id: str | None,
) -> tuple[list[Session], int]:
    """Apply filters, paginate, and return sessions with total count.

    Args:
        db: Database session
        project_id: Optional project filter
        status: Optional status filter
        agent_slug: Optional agent slug filter
        session_type: Optional session type filter
        page: Page number (1-indexed)
        page_size: Items per page

    Returns:
        Tuple of (sessions, total_count)
    """
    from app.services.session_queries import apply_session_filters

    query, count_query = apply_session_filters(
        select(Session),
        select(func.count(Session.id)),
        project_id,
        status,
        agent_slug,
        session_type,
        parent_session_id,
        external_id,
    )

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(Session.created_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    sessions = list(result.scalars().all())

    return sessions, total


async def list_sessions_with_stats(
    db: AsyncSession,
    project_id: str | None = None,
    status: str | None = None,
    agent_slug: str | None = None,
    session_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
    parent_session_id: str | None = None,
    external_id: str | None = None,
) -> tuple[list[Session], int, dict[str, int], dict[str, int], dict[str, dict[str, int]], dict[str, int], dict[str, int]]:
    """List sessions with pagination, filtering, and statistics.

    Args:
        db: Database session
        project_id: Optional project filter
        status: Optional status filter
        agent_slug: Optional agent slug filter
        session_type: Optional session type filter
        page: Page number (1-indexed)
        page_size: Items per page

    Returns:
        Tuple of (sessions, total_count, message_counts, event_counts, token_stats, child_counts, active_child_counts)
    """
    from app.services.session_queries import fetch_session_statistics

    sessions, total = await _fetch_filtered_sessions(
        db,
        project_id,
        status,
        agent_slug,
        session_type,
        page,
        page_size,
        parent_session_id,
        external_id,
    )

    session_ids = [s.id for s in sessions]
    msg_counts, event_counts, token_stats, child_counts, active_child_counts = await fetch_session_statistics(db, session_ids)

    return sessions, total, msg_counts, event_counts, token_stats, child_counts, active_child_counts


async def fork_session_at_turn(
    db: AsyncSession,
    parent: Session,
    fork_at_turn: int | None,
) -> tuple[str, int, int]:
    """Fork a session at a specific turn.

    Args:
        db: Database session
        parent: Parent session with events loaded
        fork_at_turn: Optional turn number to fork at

    Returns:
        Tuple of (new_session_id, fork_point_turn, message_count)
    """
    from app.services.session_branching import (
        copy_events_to_forked_session,
        create_forked_session,
        prepare_fork_data,
    )

    sorted_events = sorted(parent.events, key=lambda x: (x.turn, x.sequence))
    events_to_copy, fork_at = prepare_fork_data(sorted_events, fork_at_turn)

    new_session_id = str(uuid.uuid4())
    forked_session = create_forked_session(parent, new_session_id, fork_at)
    db.add(forked_session)
    copy_events_to_forked_session(db, events_to_copy, new_session_id)
    await db.commit()

    return new_session_id, fork_at, len(events_to_copy)
