"""Builder helpers and constants for feedback commands."""

from __future__ import annotations

from typing import Any

FEEDBACK_API_PATH = "/api/feedback"
FEEDBACK_SUMMARY_PATH = "/api/feedback/summary"
ALREADY_VOTED_MSG = "Already voted"
STATUS_RESOLVED = "resolved"

VALID_TYPES = ("friction", "idea", "improvement", "praise")
VALID_SEVERITIES = ("low", "medium", "high")
VALID_STATUSES = ("open", "acknowledged", "resolved", "wont_fix", "archived", "active")
VALID_SORTS = ("votes", "newest", "oldest")


def build_report_body(
    component_id: str,
    feedback_type: str,
    title: str,
    project_id: str,
    *,
    description: str | None,
    severity: str | None,
    session_id: str | None,
    agent_slug: str | None,
    model_used: str | None,
    session_type: str | None,
    vote_if_duplicate: bool,
) -> dict[str, Any]:
    """Build the request body for creating a feedback item."""
    body: dict[str, Any] = {
        "component_id": component_id,
        "feedback_type": feedback_type,
        "title": title,
        "project_id": project_id,
    }
    if description:
        body["description"] = description
    if severity:
        body["severity"] = severity
    if session_id:
        body["session_id"] = session_id
    if agent_slug:
        body["agent_slug"] = agent_slug
    if model_used:
        body["model_used"] = model_used
    if session_type:
        body["session_type"] = session_type
    if vote_if_duplicate:
        body["vote_if_duplicate"] = True
    return body


def build_filter_params(
    sort: str,
    limit: int,
    *,
    component_id: str | None = None,
    feedback_type: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Build query parameters for feedback list/search requests."""
    params: dict[str, Any] = {"sort": sort, "limit": limit}
    if query:
        params["query"] = query
    if component_id:
        params["component_id"] = component_id
    if feedback_type:
        params["feedback_type"] = feedback_type
    if status:
        params["status"] = status
    if project_id:
        params["project_id"] = project_id
    return params


def build_vote_body(
    session_id: str,
    *,
    comment: str | None,
    agent_slug: str | None,
    model_used: str | None,
) -> dict[str, Any]:
    """Build the request body for voting on a feedback item."""
    body: dict[str, Any] = {"session_id": session_id}
    if comment:
        body["comment"] = comment
    if agent_slug:
        body["agent_slug"] = agent_slug
    if model_used:
        body["model_used"] = model_used
    return body


def build_merge_body(target_item_id: str) -> dict[str, Any]:
    """Build the request body for merging a feedback item into a canonical item."""
    return {"target_item_id": target_item_id}


def build_summary_params(days: int, *, project_id: str | None = None) -> dict[str, Any]:
    """Build query parameters for the feedback summary endpoint."""
    params: dict[str, Any] = {"days": days}
    if project_id:
        params["project_id"] = project_id
    return params
