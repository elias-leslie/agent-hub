"""Canonical workflow helpers for Agent Hub clients."""

from __future__ import annotations

from typing import Any

import httpx

from agent_hub._utils import handle_error
from agent_hub.exceptions import ClientDisabledError


def build_workflow_payload(
    *,
    project_id: str,
    shared_context: str | None = None,
    external_id: str | None = None,
    trace_id: str | None = None,
    clarify: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    execute: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    qa: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build canonical workflow payload."""

    payload: dict[str, Any] = {"project_id": project_id}
    if shared_context:
        payload["shared_context"] = shared_context
    if external_id:
        payload["external_id"] = external_id
    if trace_id:
        payload["trace_id"] = trace_id
    if clarify is not None:
        payload["clarify"] = clarify
    if plan is not None:
        payload["plan"] = plan
    if execute is not None:
        payload["execute"] = execute
    if review is not None:
        payload["review"] = review
    if qa is not None:
        payload["qa"] = qa
    return payload


def handle_workflow_response(
    response: httpx.Response,
    client_instance: Any,
) -> dict[str, Any]:
    """Handle canonical workflow response and update client state if disabled."""

    if not response.is_success:
        try:
            handle_error(response)
        except ClientDisabledError as exc:
            client_instance._disabled = True
            client_instance._disabled_reason = exc.reason
            raise

    return response.json()
