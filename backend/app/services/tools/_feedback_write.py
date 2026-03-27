"""Write feedback tool actions: resolve, vote, merge, delete."""

from __future__ import annotations

import logging

from app.services.tools._feedback_utils import db_session, resolve_id, resolve_verb

logger = logging.getLogger(__name__)


async def resolve_item(item_id: str | None, status: str | None, resolution_note: str | None) -> str:
    """Update a feedback item status by ID."""
    if not item_id:
        return "Error: item_id is required for resolve action"
    try:
        from app.services.feedback_storage import update_feedback_status

        async with db_session() as db:
            full_id = await resolve_id(db, item_id)
            if not full_id:
                return f"Error: No feedback item found matching '{item_id}'"
            updated = await update_feedback_status(
                db, full_id, status=status or "resolved", resolution_note=resolution_note,
            )
            await db.commit()

        if not updated:
            return f"Error: Could not update feedback item '{item_id}'"
        return (f"{resolve_verb(updated.status)}: {str(updated.id)[:8]} — "
                f"{updated.title} ({updated.status})")
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("manage_feedback resolve failed")
        return f"Error resolving feedback: {e}"


async def vote_item(item_id: str | None, comment: str | None) -> str:
    """Vote on a feedback item by ID."""
    if not item_id:
        return "Error: item_id is required for vote action"
    try:
        from app.services.feedback_storage import vote_on_item

        async with db_session() as db:
            full_id = await resolve_id(db, item_id)
            if not full_id:
                return f"Error: No feedback item found matching '{item_id}'"
            vote = await vote_on_item(
                db, item_id=full_id, session_id="persona-heartbeat",
                comment=comment, agent_slug="persona",
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


async def merge_items(source_item_id: str | None, target_item_id: str | None) -> str:
    """Merge a duplicate feedback item into a canonical item."""
    if not source_item_id:
        return "Error: item_id is required for merge action"
    if not target_item_id:
        return "Error: target_item_id is required for merge action"
    try:
        from app.services.feedback_storage import merge_feedback_items

        async with db_session() as db:
            full_source_id = await resolve_id(db, source_item_id)
            if not full_source_id:
                return f"Error: No feedback item found matching '{source_item_id}'"
            full_target_id = await resolve_id(db, target_item_id)
            if not full_target_id:
                return f"Error: No feedback item found matching '{target_item_id}'"
            merged = await merge_feedback_items(
                db, source_item_id=full_source_id, target_item_id=full_target_id,
            )
            await db.commit()

        if merged is None:
            return "Error: Could not merge feedback items"
        return (f"Merged: {str(full_source_id)[:8]} -> {str(full_target_id)[:8]} "
                f"({merged.vote_count} votes)")
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("manage_feedback merge failed")
        return f"Error merging feedback: {e}"


async def delete_item(item_id: str | None) -> str:
    """Delete a feedback item and its votes."""
    if not item_id:
        return "Error: item_id is required for delete action"
    try:
        from app.services.feedback_storage import delete_feedback_item, get_feedback_item

        async with db_session() as db:
            full_id = await resolve_id(db, item_id)
            if not full_id:
                return f"Error: No feedback item found matching '{item_id}'"
            item = await get_feedback_item(db, full_id)
            title = item.title if item else item_id
            deleted = await delete_feedback_item(db, full_id)
            await db.commit()

        if not deleted:
            return f"Error: Could not delete feedback item '{item_id}'"
        return f"Deleted: {str(full_id)[:8]} — {title}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("manage_feedback delete failed")
        return f"Error deleting feedback: {e}"
