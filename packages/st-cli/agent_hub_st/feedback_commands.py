"""Implementation of st feedback subcommands."""

from __future__ import annotations

from typing import Any

import typer
from st_sdk.output import output_error, output_json

from .feedback_api import feedback_request
from .feedback_formatters import (
    output_duplicate_candidates,
    output_feedback_created,
    output_feedback_deduped,
    output_feedback_detail,
    output_feedback_existing,
    output_feedback_list,
    output_feedback_voted,
    output_summary,
)
from .feedback_helpers import (
    ALREADY_VOTED_MSG,
    FEEDBACK_API_PATH,
    FEEDBACK_SUMMARY_PATH,
    STATUS_RESOLVED,
    build_filter_params,
    build_report_body,
    build_summary_params,
    build_vote_body,
)
from .feedback_validators import (
    validate_component_id,
    validate_feedback_type,
    validate_limit,
    validate_severity,
    validate_sort,
)


def report_impl(
    component_id: str,
    title: str,
    *,
    feedback_type: str = "friction",
    severity: str | None = None,
    description: str | None = None,
    project_id: str = "summitflow",
    session_id: str | None = None,
    agent_slug: str | None = None,
    model_used: str | None = None,
    session_type: str | None = None,
    vote_if_duplicate: bool = False,
) -> None:
    """Create a new feedback item."""
    validate_component_id(component_id)
    validate_feedback_type(feedback_type)
    validate_severity(severity)
    body = build_report_body(
        component_id, feedback_type, title, project_id,
        description=description, severity=severity, session_id=session_id,
        agent_slug=agent_slug, model_used=model_used, session_type=session_type,
        vote_if_duplicate=vote_if_duplicate,
    )
    result = feedback_request("POST", FEEDBACK_API_PATH, json=body)
    candidates = result.get("duplicate_candidates", [])
    if candidates:
        output_duplicate_candidates(candidates)
    if not result.get("created", True):
        if result.get("voted"):
            output_feedback_deduped(result.get("item", {}))
            return
        output_feedback_existing(result.get("item", {}))
        return
    output_feedback_created(result.get("item", {}))


def search_impl(
    query: str,
    *,
    component_id: str | None = None,
    feedback_type: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    sort: str = "votes",
    limit: int = 20,
) -> None:
    """Search feedback items."""
    validate_limit(limit)
    validate_sort(sort)
    params = build_filter_params(
        sort, limit, query=query, component_id=component_id,
        feedback_type=feedback_type, status=status or "active", project_id=project_id,
    )
    result = feedback_request("GET", FEEDBACK_API_PATH, params=params)
    items = result.get("items", [])
    output_feedback_list(items, result.get("total", len(items)))


def list_impl(
    *,
    component_id: str | None = None,
    feedback_type: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    sort: str = "votes",
    limit: int = 50,
) -> None:
    """List feedback items."""
    validate_limit(limit)
    validate_sort(sort)
    params = build_filter_params(
        sort, limit, component_id=component_id, feedback_type=feedback_type,
        status=status or "active", project_id=project_id,
    )
    result = feedback_request("GET", FEEDBACK_API_PATH, params=params)
    items = result.get("items", [])
    output_feedback_list(items, result.get("total", len(items)))


def get_impl(item_id: str, *, json_output: bool = False) -> None:
    """Get feedback item details with votes."""
    result = feedback_request("GET", f"{FEEDBACK_API_PATH}/{item_id}")
    if json_output:
        output_json(result)
        return
    output_feedback_detail(result)


def vote_impl(
    item_id: str,
    *,
    session_id: str | None = None,
    comment: str | None = None,
    agent_slug: str | None = None,
    model_used: str | None = None,
) -> None:
    """Vote on a feedback item."""
    if not session_id:
        output_error("--session-id is required for voting")
        raise typer.Exit(1)
    body = build_vote_body(session_id, comment=comment, agent_slug=agent_slug, model_used=model_used)
    result = feedback_request("POST", f"{FEEDBACK_API_PATH}/{item_id}/vote", json=body)
    if result.get("message") == ALREADY_VOTED_MSG:
        print(f"VOTE:ALREADY_VOTED:{item_id[:8]}|{session_id[:8]}")
        return
    output_feedback_voted(feedback_request("GET", f"{FEEDBACK_API_PATH}/{item_id}"))


def resolve_impl(item_id: str, *, note: str | None = None) -> None:
    """Resolve a feedback item."""
    body: dict[str, Any] = {"status": STATUS_RESOLVED}
    if note:
        body["resolution_note"] = note
    result = feedback_request("PATCH", f"{FEEDBACK_API_PATH}/{item_id}", json=body)
    print(f"FEEDBACK:RESOLVED:{result.get('id', item_id)[:8]}|{result.get('title', '')}")


def delete_impl(item_id: str) -> None:
    """Delete a feedback item."""
    feedback_request("DELETE", f"{FEEDBACK_API_PATH}/{item_id}")
    print(f"FEEDBACK:DELETED:{item_id[:8]}")


def archive_impl(item_id: str, *, note: str | None = None) -> None:
    """Archive a feedback item."""
    body: dict[str, Any] = {"status": "archived"}
    if note:
        body["resolution_note"] = note
    result = feedback_request("PATCH", f"{FEEDBACK_API_PATH}/{item_id}", json=body)
    print(f"FEEDBACK:ARCHIVED:{result.get('id', item_id)[:8]}|{result.get('title', '')}")


def merge_impl(item_id: str, target_item_id: str) -> None:
    """Merge a duplicate feedback item into a canonical feedback item."""
    from .feedback_helpers import build_merge_body

    result = feedback_request("POST", f"{FEEDBACK_API_PATH}/{item_id}/merge", json=build_merge_body(target_item_id))
    print(
        f"FEEDBACK:MERGED:{item_id[:8]}->{result.get('id', target_item_id)[:8]}|"
        f"{result.get('title', '')}"
    )


def summary_impl(*, project_id: str | None = None, days: int = 30) -> None:
    """Get feedback summary."""
    params = build_summary_params(days, project_id=project_id)
    output_summary(feedback_request("GET", FEEDBACK_SUMMARY_PATH, params=params))
