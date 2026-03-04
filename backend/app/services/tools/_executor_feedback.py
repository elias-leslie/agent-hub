"""Feedback triage tool implementation for DirectToolExecutor."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def manage_feedback(
    action: str,
    item_id: str | None = None,
    query: str | None = None,
    component_id: str | None = None,
    feedback_type: str | None = None,
    status: str | None = None,
    resolution_note: str | None = None,
    comment: str | None = None,
    project_id: str | None = None,
    limit: int = 20,
) -> str:
    """Triage feedback items: search, resolve, or vote."""
    if action == "search":
        return await _search(query, component_id, feedback_type, project_id, limit)
    if action == "resolve":
        return await _resolve(item_id, status, resolution_note)
    if action == "vote":
        return await _vote(item_id, comment)
    return (
        f"Error: Unknown action '{action}'. "
        "Use search/resolve/vote."
    )


async def _search(
    query: str | None,
    component_id: str | None,
    feedback_type: str | None,
    project_id: str | None,
    limit: int,
) -> str:
    """Search feedback items and return a concise text table."""
    try:
        from app.db import async_session
        from app.services.feedback_storage import search_feedback_items

        async with async_session() as db:
            items = await search_feedback_items(
                db,
                query=query,
                component_id=component_id,
                feedback_type=feedback_type,
                status="open",
                project_id=project_id,
                sort="votes",
                limit=limit,
            )

        if not items:
            return "(No open feedback items matching filters)"

        lines = [f"Open feedback items ({len(items)}):", ""]
        lines.append(f"{'ID':>8}  {'Type':<11}  {'Component':<20}  {'Votes':>5}  Title")
        lines.append("-" * 78)
        for item in items:
            short_id = str(item.id)[:8]
            lines.append(
                f"{short_id:>8}  {item.feedback_type:<11}  "
                f"{item.component_id:<20}  {item.vote_count:>5}  "
                f"{(item.title or '')[:40]}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.exception("manage_feedback search failed")
        return f"Error searching feedback: {e}"


async def _resolve(
    item_id: str | None,
    status: str | None,
    resolution_note: str | None,
) -> str:
    """Resolve a feedback item by ID."""
    if not item_id:
        return "Error: item_id is required for resolve action"

    try:
        from app.db import async_session
        from app.services.feedback_storage import resolve_feedback_id, update_feedback_status

        async with async_session() as db:
            full_id = await resolve_feedback_id(db, item_id)
            if not full_id:
                return f"Error: No feedback item found matching '{item_id}'"

            updated = await update_feedback_status(
                db,
                full_id,
                status=status or "resolved",
                resolution_note=resolution_note,
            )
            await db.commit()

        if not updated:
            return f"Error: Could not update feedback item '{item_id}'"

        return f"Resolved: {str(updated.id)[:8]} — {updated.title}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("manage_feedback resolve failed")
        return f"Error resolving feedback: {e}"


async def _vote(item_id: str | None, comment: str | None) -> str:
    """Vote on a feedback item by ID."""
    if not item_id:
        return "Error: item_id is required for vote action"

    try:
        from app.db import async_session
        from app.services.feedback_storage import resolve_feedback_id, vote_on_item

        async with async_session() as db:
            full_id = await resolve_feedback_id(db, item_id)
            if not full_id:
                return f"Error: No feedback item found matching '{item_id}'"

            vote = await vote_on_item(
                db,
                item_id=full_id,
                session_id="persona-heartbeat",
                comment=comment,
                agent_slug="persona",
            )
            await db.commit()

        if vote is None:
            return f"Already voted on {item_id[:8]}"

        return f"Voted on: {item_id[:8]} — vote recorded"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("manage_feedback vote failed")
        return f"Error voting on feedback: {e}"
