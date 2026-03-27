"""Feedback triage tool implementation for DirectToolExecutor."""

from __future__ import annotations

from app.services.tools._feedback_read import get_item, list_items, search, summarize
from app.services.tools._feedback_write import delete_item, merge_items, resolve_item, vote_item

_ACTIONS = "search/list/get/summary/resolve/archive/vote/merge/delete"


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
        return await search(query, component_id, feedback_type, project_id, limit)
    if action == "list":
        return await list_items(query, component_id, feedback_type, status, project_id, sort, limit)
    if action == "get":
        return await get_item(item_id)
    if action == "summary":
        return await summarize(project_id, days)
    if action == "resolve":
        return await resolve_item(item_id, status, resolution_note)
    if action == "archive":
        return await resolve_item(item_id, "archived", resolution_note)
    if action == "vote":
        return await vote_item(item_id, comment)
    if action == "merge":
        return await merge_items(item_id, target_item_id)
    if action == "delete":
        return await delete_item(item_id)
    return f"Error: Unknown action '{action}'. Use {_ACTIONS}."
