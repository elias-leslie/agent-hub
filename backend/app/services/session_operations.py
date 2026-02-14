"""Session CRUD operations - business logic for session lifecycle."""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.agent_routing import resolve_agent
from app.services.events import publish_session_start

logger = logging.getLogger(__name__)


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
    """
    final_session_id = session_id or str(uuid.uuid4())
    final_provider = provider
    final_model = model

    # Resolve agent if provided
    if agent_slug:
        resolved = await resolve_agent(agent_slug, db)
        final_provider = resolved.provider
        final_model = resolved.model

    session = Session(
        id=final_session_id,
        project_id=project_id,
        provider=final_provider,
        model=final_model,
        status="active",
        session_type=session_type,
    )

    db.add(session)
    await db.commit()
    await db.refresh(session)

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

    session.status = "completed"
    await db.commit()

    # Dispatch async summary generation for agentic sessions
    # CC sessions are summarized by the Stop hook; this covers API sessions
    # (st autocode, st complete) that close via this path.
    await _dispatch_summary_on_close(session)

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


async def list_sessions_with_stats(
    db: AsyncSession,
    project_id: str | None = None,
    status: str | None = None,
    agent_slug: str | None = None,
    session_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Session], int, dict[str, int], dict[str, dict[str, int]]]:
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
        Tuple of (sessions, total_count, message_counts, token_stats)
    """
    from app.services.session_queries import apply_session_filters, fetch_session_statistics

    # Build and filter queries
    query, count_query = apply_session_filters(
        select(Session),
        select(func.count(Session.id)),
        project_id,
        status,
        agent_slug,
        session_type,
    )

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    offset = (page - 1) * page_size
    query = query.order_by(Session.created_at.desc()).offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    sessions = list(result.scalars().all())

    # Fetch statistics
    session_ids = [s.id for s in sessions]
    msg_counts, token_stats = await fetch_session_statistics(db, session_ids)

    return sessions, total, msg_counts, token_stats


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


async def _dispatch_summary_on_close(session: Session) -> None:
    """Dispatch async summary generation via Hatchet when a session closes.

    Non-blocking: fires and forgets. The quality gate in generate_session_summary
    (MIN_TRANSCRIPT_LINES=20) will skip trivial sessions automatically.
    """
    try:
        from app.workflows.summary import SummaryInput, session_summary_task

        await session_summary_task.aio_run_no_wait(
            input=SummaryInput(
                session_id=session.id,
                branch=session.summary_branch,
                is_worktree=session.summary_is_worktree,
            ),
        )
        logger.info("Dispatched summary task for closed session %s", session.id)
    except Exception as e:
        # Never block session close on summary failure
        logger.warning("Failed to dispatch summary for session %s: %s", session.id, e)
