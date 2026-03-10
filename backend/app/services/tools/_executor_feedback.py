"""Feedback triage tool implementation for DirectToolExecutor."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def manage_feedback(
    action: str,
    item_id: str | None = None,
    target_item_id: str | None = None,
    query: str | None = None,
    component_id: str | None = None,
    feedback_type: str | None = None,
    status: str | None = None,
    resolution_note: str | None = None,
    comment: str | None = None,
    project_id: str | None = None,
    sort: str = "votes",
    limit: int = 20,
    days: int = 30,
) -> str:
    """Review and manage feedback items for governance and triage."""
    if action == "search":
        return await _search(query, component_id, feedback_type, project_id, limit)
    if action == "list":
        return await _list(query, component_id, feedback_type, status, project_id, sort, limit)
    if action == "get":
        return await _get(item_id)
    if action == "summary":
        return await _summary(project_id, days)
    if action == "resolve":
        return await _resolve(item_id, status, resolution_note)
    if action == "archive":
        return await _resolve(item_id, "archived", resolution_note)
    if action == "vote":
        return await _vote(item_id, comment)
    if action == "merge":
        return await _merge(item_id, target_item_id)
    if action == "delete":
        return await _delete(item_id)
    return (
        f"Error: Unknown action '{action}'. "
        "Use search/list/get/summary/resolve/archive/vote/merge/delete."
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
                status="active",
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


async def _list(
    query: str | None,
    component_id: str | None,
    feedback_type: str | None,
    status: str | None,
    project_id: str | None,
    sort: str,
    limit: int,
) -> str:
    """List feedback items with optional status filter."""
    try:
        from app.db import async_session
        from app.services.feedback_storage import search_feedback_items

        async with async_session() as db:
            items = await search_feedback_items(
                db,
                query=query,
                component_id=component_id,
                feedback_type=feedback_type,
                status=status or "active",
                project_id=project_id,
                sort=sort,
                limit=limit,
            )

        if not items:
            return "(No feedback items matching filters)"

        lines = [f"Feedback items ({len(items)}):", ""]
        lines.append(
            f"{'ID':>8}  {'Status':<12}  {'Type':<11}  {'Component':<20}  {'Votes':>5}  Title"
        )
        lines.append("-" * 92)
        for item in items:
            short_id = str(item.id)[:8]
            lines.append(
                f"{short_id:>8}  {item.status:<12}  {item.feedback_type:<11}  "
                f"{item.component_id:<20}  {item.vote_count:>5}  "
                f"{(item.title or '')[:36]}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.exception("manage_feedback list failed")
        return f"Error listing feedback: {e}"


async def _get(item_id: str | None) -> str:
    """Get detailed feedback item information including recent votes."""
    if not item_id:
        return "Error: item_id is required for get action"

    try:
        from app.db import async_session
        from app.services.feedback_storage import (
            get_feedback_item,
            get_feedback_votes,
            resolve_feedback_id,
        )

        async with async_session() as db:
            full_id = await resolve_feedback_id(db, item_id)
            if not full_id:
                return f"Error: No feedback item found matching '{item_id}'"
            item = await get_feedback_item(db, full_id)
            if item is None:
                return f"Error: Feedback item '{item_id}' disappeared during lookup"
            votes = await get_feedback_votes(db, full_id)

        lines = [
            f"ID: {item.id}",
            f"Title: {item.title}",
            f"Status: {item.status}",
            f"Type: {item.feedback_type}",
            f"Component: {item.component_id}",
            f"Project: {item.project_id}",
            f"Severity: {item.severity or 'n/a'}",
            f"Votes: {item.vote_count}",
            f"Created: {item.created_at.isoformat() if item.created_at else 'unknown'}",
        ]
        if item.linked_task_id:
            lines.append(f"Linked task: {item.linked_task_id}")
        if item.description:
            lines.extend(["Description:", item.description])
        if item.resolution_note:
            lines.extend(["Resolution note:", item.resolution_note])
        if votes:
            lines.append("Votes:")
            for vote in votes[:5]:
                comment = f" — {vote.comment}" if vote.comment else ""
                lines.append(
                    f"- {vote.session_id} by {vote.agent_slug or 'unknown'}"
                    f"{comment}"
                )
        else:
            lines.append("Votes: NONE")
        return "\n".join(lines)
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("manage_feedback get failed")
        return f"Error getting feedback: {e}"


async def _summary(project_id: str | None, days: int) -> str:
    """Summarize feedback clusters for governance review."""
    try:
        from app.db import async_session
        from app.services.feedback_storage import get_feedback_summary

        async with async_session() as db:
            summary = await get_feedback_summary(db, project_id=project_id, days=days)

        counts = summary.get("counts_by_type_status", [])
        type_counts: dict[str, int] = {}
        unresolved = 0
        for row in counts:
            if row.get("status") not in {"open", "acknowledged"}:
                continue
            ft = row.get("feedback_type", "unknown")
            count = int(row.get("count", 0))
            unresolved += count
            type_counts[ft] = type_counts.get(ft, 0) + count

        lines = [f"Feedback summary ({days}d):"]
        lines.append(
            f"- unresolved={unresolved} total_items={summary.get('total_items', 0)}"
        )
        if type_counts:
            breakdown = ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items()))
            lines.append(f"- by_type: {breakdown}")

        hot_components = [
            row for row in summary.get("by_component", [])
            if int(row.get("open_count", 0) or 0) > 0
        ][:5]
        if hot_components:
            lines.append("- hotspots:")
            for row in hot_components:
                lines.append(
                    f"  {row['component_id']}: open={row['open_count']} "
                    f"resolved={row['resolved_count']} votes={row['total_votes'] or 0}"
                )

        top_items = summary.get("top_unresolved", [])[:5]
        if top_items:
            lines.append("- top_unresolved:")
            for item in top_items:
                lines.append(
                    f"  {str(item['id'])[:8]} {item['feedback_type']} "
                    f"{item['component_id']} votes={item['vote_count']} "
                    f"{(item['title'] or '')[:48]}"
                )

        return "\n".join(lines)
    except Exception as e:
        logger.exception("manage_feedback summary failed")
        return f"Error summarizing feedback: {e}"


async def _resolve(
    item_id: str | None,
    status: str | None,
    resolution_note: str | None,
) -> str:
    """Update a feedback item status by ID."""
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

        if updated.status == "archived":
            verb = "Archived"
        elif updated.status == "resolved":
            verb = "Resolved"
        else:
            verb = "Updated"
        return f"{verb}: {str(updated.id)[:8]} — {updated.title} ({updated.status})"
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


async def _merge(source_item_id: str | None, target_item_id: str | None) -> str:
    """Merge a duplicate feedback item into a canonical item."""
    if not source_item_id:
        return "Error: item_id is required for merge action"
    if not target_item_id:
        return "Error: target_item_id is required for merge action"

    try:
        from app.db import async_session
        from app.services.feedback_storage import merge_feedback_items, resolve_feedback_id

        async with async_session() as db:
            full_source_id = await resolve_feedback_id(db, source_item_id)
            if not full_source_id:
                return f"Error: No feedback item found matching '{source_item_id}'"
            full_target_id = await resolve_feedback_id(db, target_item_id)
            if not full_target_id:
                return f"Error: No feedback item found matching '{target_item_id}'"
            merged = await merge_feedback_items(
                db,
                source_item_id=full_source_id,
                target_item_id=full_target_id,
            )
            await db.commit()

        if merged is None:
            return "Error: Could not merge feedback items"

        return (
            f"Merged: {str(full_source_id)[:8]} -> {str(full_target_id)[:8]} "
            f"({merged.vote_count} votes)"
        )
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("manage_feedback merge failed")
        return f"Error merging feedback: {e}"


async def _delete(item_id: str | None) -> str:
    """Delete a feedback item and its votes."""
    if not item_id:
        return "Error: item_id is required for delete action"

    try:
        from app.db import async_session
        from app.services.feedback_storage import (
            delete_feedback_item,
            get_feedback_item,
            resolve_feedback_id,
        )

        async with async_session() as db:
            full_id = await resolve_feedback_id(db, item_id)
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
