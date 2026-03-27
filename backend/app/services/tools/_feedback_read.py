"""Read-only feedback tool actions: search, list, get, summary."""

from __future__ import annotations

import logging

from app.services.tools._feedback_utils import db_session, resolve_id

logger = logging.getLogger(__name__)


async def search(
    query: str | None,
    component_id: str | None,
    feedback_type: str | None,
    project_id: str | None,
    limit: int,
) -> str:
    """Search open feedback items and return a text table."""
    try:
        from app.services.feedback_storage import search_feedback_items

        async with db_session() as db:
            items = await search_feedback_items(
                db, query=query, component_id=component_id, feedback_type=feedback_type,
                status="active", project_id=project_id, sort="votes", limit=limit,
            )
        if not items:
            return "(No open feedback items matching filters)"
        header = f"{'ID':>8}  {'Type':<11}  {'Component':<20}  {'Votes':>5}  Title"
        rows = [
            f"{str(i.id)[:8]:>8}  {i.feedback_type:<11}  {i.component_id:<20}  "
            f"{i.vote_count:>5}  {(i.title or '')[:40]}"
            for i in items
        ]
        return "\n".join([f"Open feedback items ({len(items)}):", "", header, "-" * 78, *rows])
    except Exception as e:
        logger.exception("manage_feedback search failed")
        return f"Error searching feedback: {e}"


async def list_items(
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
        from app.services.feedback_storage import search_feedback_items

        async with db_session() as db:
            items = await search_feedback_items(
                db, query=query, component_id=component_id, feedback_type=feedback_type,
                status=status or "active", project_id=project_id, sort=sort, limit=limit,
            )
        if not items:
            return "(No feedback items matching filters)"
        header = f"{'ID':>8}  {'Status':<12}  {'Type':<11}  {'Component':<20}  {'Votes':>5}  Title"
        rows = [
            f"{str(i.id)[:8]:>8}  {i.status:<12}  {i.feedback_type:<11}  "
            f"{i.component_id:<20}  {i.vote_count:>5}  {(i.title or '')[:36]}"
            for i in items
        ]
        return "\n".join([f"Feedback items ({len(items)}):", "", header, "-" * 92, *rows])
    except Exception as e:
        logger.exception("manage_feedback list failed")
        return f"Error listing feedback: {e}"


async def get_item(item_id: str | None) -> str:
    """Get detailed feedback item information including recent votes."""
    if not item_id:
        return "Error: item_id is required for get action"
    try:
        from app.services.feedback_storage import get_feedback_item, get_feedback_votes

        async with db_session() as db:
            full_id = await resolve_id(db, item_id)
            if not full_id:
                return f"Error: No feedback item found matching '{item_id}'"
            item = await get_feedback_item(db, full_id)
            if item is None:
                return f"Error: Feedback item '{item_id}' disappeared during lookup"
            votes = await get_feedback_votes(db, full_id)

        created = item.created_at.isoformat() if item.created_at else "unknown"
        lines = [
            f"ID: {item.id}", f"Title: {item.title}", f"Status: {item.status}",
            f"Type: {item.feedback_type}", f"Component: {item.component_id}",
            f"Project: {item.project_id}", f"Severity: {item.severity or 'n/a'}",
            f"Votes: {item.vote_count}", f"Created: {created}",
        ]
        if item.linked_task_id:
            lines.append(f"Linked task: {item.linked_task_id}")
        if item.description:
            lines.extend(["Description:", item.description])
        if item.resolution_note:
            lines.extend(["Resolution note:", item.resolution_note])
        if votes:
            lines.append("Votes:")
            for v in votes[:5]:
                lines.append(f"- {v.session_id} by {v.agent_slug or 'unknown'}"
                              + (f" — {v.comment}" if v.comment else ""))
        else:
            lines.append("Votes: NONE")
        return "\n".join(lines)
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("manage_feedback get failed")
        return f"Error getting feedback: {e}"


async def summarize(project_id: str | None, days: int) -> str:
    """Summarize feedback clusters for governance review."""
    try:
        from app.services.feedback_storage import get_feedback_summary

        async with db_session() as db:
            summary = await get_feedback_summary(db, project_id=project_id, days=days)

        type_counts: dict[str, int] = {}
        unresolved = 0
        for row in summary.get("counts_by_type_status", []):
            if row.get("status") not in {"open", "acknowledged"}:
                continue
            ft = str(row.get("feedback_type", "unknown"))
            count = int(row.get("count", 0))
            unresolved += count
            type_counts[ft] = type_counts.get(ft, 0) + count

        lines = [
            f"Feedback summary ({days}d):",
            f"- unresolved={unresolved} total_items={summary.get('total_items', 0)}",
        ]
        if type_counts:
            lines.append("- by_type: " + ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items())))

        hot = [r for r in summary.get("by_component", []) if int(r.get("open_count", 0) or 0) > 0][:5]
        if hot:
            lines.append("- hotspots:")
            for r in hot:
                lines.append(f"  {r['component_id']}: open={r['open_count']} "
                              f"resolved={r['resolved_count']} votes={r['total_votes'] or 0}")

        top = summary.get("top_unresolved", [])[:5]
        if top:
            lines.append("- top_unresolved:")
            for item in top:
                lines.append(f"  {str(item['id'])[:8]} {item['feedback_type']} "
                              f"{item['component_id']} votes={item['vote_count']} "
                              f"{(item['title'] or '')[:48]}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("manage_feedback summary failed")
        return f"Error summarizing feedback: {e}"
