"""Focused tests for session response/list transformations."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Session
from app.services.session_transforms import build_session_list_items, build_session_response


def _session(**overrides: object) -> Session:
    payload = {
        "id": "sess-1",
        "project_id": "agent-hub",
        "provider": "codex",
        "model": "codex/gpt-5.4",
        "status": "active",
        "session_type": "agent",
        "provider_metadata": {"repo_root": "/srv/workspaces/projects/agent-hub"},
        "models_used": ["codex/gpt-5.4"],
        "providers_used": ["codex"],
    }
    payload.update(overrides)
    session = Session(**payload)
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)
    return session


def test_build_session_list_items_derives_scope_confidence_from_paths() -> None:
    session = _session(
        observed_write_paths=["backend/app/services/session_scope.py"],
        scope_confidence="unknown",
    )

    item = build_session_list_items([session], {}, {})[0]

    assert item.scope_confidence == "observed_write"


def test_build_session_response_derives_scope_confidence_from_paths() -> None:
    session = _session(
        observed_read_paths=["backend/app/services/session_scope.py"],
        scope_confidence="unknown",
    )

    response = build_session_response(session)

    assert response.scope_confidence == "observed_read"


def test_build_session_list_items_exposes_batch_task_ids() -> None:
    session = _session(
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "batch_task_ids": ["task-a", "task-b"],
        }
    )

    item = build_session_list_items([session], {}, {})[0]

    assert item.batch_task_ids == ["task-a", "task-b"]
