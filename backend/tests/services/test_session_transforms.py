"""Focused tests for session response/list transformations."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.models import Session
from app.models.session import SessionEventType
from app.services.session_transforms import (
    build_session_list_items,
    build_session_response,
    convert_messages_to_response,
)


def _session(**overrides: object) -> Session:
    payload: dict[str, object] = {
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


def test_session_responses_expose_only_allow_listed_external_identity() -> None:
    session = _session(
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "external_identity": {
                "harness": "codex",
                "launcher": "aico",
                "display_identity": "Codex · Rootfall",
                "runtime_session_id": "runtime-123",
                "agent_path": "/root/codex-1",
                "aico_session_id": "aico-session-1",
                "aico_widget_id": "widget-1",
                "aico_project_id": "rootfall",
                "project_mapping_state": "mapped",
                "prompt": "do not expose",
                "secret": "do not expose",
                "model_content": "do not expose",
            },
            "credentials": "do not expose",
            "provider_prompt": "do not expose",
        }
    )

    response = build_session_response(session)
    item = build_session_list_items([session], {}, {})[0]
    expected = {
        "harness": "codex",
        "launcher": "aico",
        "display_identity": "Codex · Rootfall",
        "runtime_session_id": "runtime-123",
        "agent_path": "/root/codex-1",
        "aico_session_id": "aico-session-1",
        "aico_widget_id": "widget-1",
        "aico_project_id": "rootfall",
        "project_mapping_state": "mapped",
    }

    assert response.external_identity is not None
    assert response.external_identity.model_dump(exclude_none=True) == expected
    assert item.external_identity is not None
    assert item.external_identity.model_dump(exclude_none=True) == expected
    response_payload = response.model_dump()
    assert "provider_metadata" not in response_payload
    assert set(response_payload["external_identity"]) == set(expected)


def test_external_identity_prefers_nested_and_supports_bounded_legacy_keys() -> None:
    session = _session(
        provider_metadata={
            "harness": "legacy-harness",
            "launcher": "legacy-launcher",
            "runtime_session_id": "legacy-runtime",
            "agent_path": "x" * 513,
            "external_identity": {
                "harness": "nested-harness",
                "launcher": "nested-launcher",
            },
        }
    )

    response = build_session_response(session)

    assert response.external_identity is not None
    assert response.external_identity.model_dump(exclude_none=True) == {
        "harness": "nested-harness",
        "launcher": "nested-launcher",
        "runtime_session_id": "legacy-runtime",
    }


def test_build_session_list_items_exposes_batch_task_ids() -> None:
    session = _session(
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "batch_task_ids": ["task-a", "task-b"],
        }
    )

    item = build_session_list_items([session], {}, {})[0]

    assert item.batch_task_ids == ["task-a", "task-b"]


def test_build_session_list_items_exposes_message_and_event_counts_separately() -> None:
    session = _session()

    item = build_session_list_items([session], {"sess-1": 2}, {}, {"sess-1": 5})[0]

    assert item.message_count == 2
    assert item.event_count == 5


def test_build_session_list_items_exposes_child_counts() -> None:
    session = _session()

    item = build_session_list_items(
        [session],
        {},
        {},
        child_counts={"sess-1": 3},
        active_child_counts={"sess-1": 1},
    )[0]

    assert item.child_session_count == 3
    assert item.active_child_session_count == 1


def test_build_session_list_items_marks_runtime_status_when_live_disagrees() -> None:
    session = _session(
        status="active",
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "live_activity": {"phase": "error", "status": "error"},
        },
    )

    item = build_session_list_items([session], {}, {})[0]

    assert item.status_source == "runtime"
    assert item.status_matches_live is False
    assert item.live_activity is not None
    assert item.live_activity.source == "runtime"


def test_build_session_response_marks_session_status_when_live_matches() -> None:
    session = _session(
        status="completed",
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "live_activity": {"phase": "completed", "status": "completed"},
        },
    )

    response = build_session_response(session, child_session_count=2, active_child_session_count=0)

    assert response.child_session_count == 2
    assert response.active_child_session_count == 0
    assert response.status_source == "session"
    assert response.status_matches_live is True


def test_build_session_list_items_classifies_benchmark_attribution() -> None:
    session = _session(
        request_source="manual/caveman-mini-baseline",
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "source_client": "summitflow",
        },
    )

    item = build_session_list_items([session], {}, {})[0]

    assert item.attribution_kind == "benchmark"
    assert item.attribution_label == "Benchmark"
    assert item.attribution_detail == "manual/caveman-mini-baseline"


def test_build_session_response_classifies_autonomous_attribution() -> None:
    session = _session(
        request_source="summitflow",
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "source_client": "summitflow",
        },
    )

    response = build_session_response(session)

    assert response.attribution_kind == "autonomous"
    assert response.attribution_label == "Autonomous"
    assert response.attribution_detail == "summitflow"


def test_convert_messages_to_response_synthesizes_incomplete_tool_turn() -> None:
    now = datetime.now(UTC)
    events = [
        SimpleNamespace(
            id="evt-tool-1",
            turn=8,
            sequence=1,
            event_type=SessionEventType.TOOL_USE,
            role=None,
            content=None,
            tool_name="bash",
            tool_input={"command": "st claim task-29753d4e"},
            tool_output=None,
            tokens=None,
            duration_ms=None,
            model_used="codex/gpt-5.4",
            agent_id="persona",
            agent_name="persona",
            created_at=now,
        ),
        SimpleNamespace(
            id="evt-tool-2",
            turn=8,
            sequence=2,
            event_type=SessionEventType.TOOL_RESULT,
            role=None,
            content="Created checkout",
            tool_name="bash",
            tool_input=None,
            tool_output={"content": "Created checkout", "is_error": False},
            tokens=None,
            duration_ms=25,
            model_used="codex/gpt-5.4",
            agent_id="persona",
            agent_name="persona",
            created_at=now,
        ),
    ]

    messages = convert_messages_to_response(events, agent_display_names={"persona": "Jenny"})

    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].agent_display_name == "Jenny"
    assert messages[0].content == "Tool activity recorded without a final assistant summary. Tools: bash."
    assert messages[0].tool_executions is not None
    assert len(messages[0].tool_executions) == 1
    assert messages[0].tool_executions[0].name == "bash"
    assert messages[0].tool_executions[0].result == "{'content': 'Created checkout', 'is_error': False}"


def test_convert_messages_to_response_keeps_real_assistant_without_synthetic_duplicate() -> None:
    now = datetime.now(UTC)
    events = [
        SimpleNamespace(
            id="evt-user",
            turn=8,
            sequence=1,
            event_type=SessionEventType.USER_MESSAGE,
            role="user",
            content="continue",
            tool_name=None,
            tool_input=None,
            tool_output=None,
            tokens=None,
            duration_ms=None,
            model_used=None,
            agent_id="persona",
            agent_name="persona",
            created_at=now,
        ),
        SimpleNamespace(
            id="evt-tool-1",
            turn=8,
            sequence=2,
            event_type=SessionEventType.TOOL_USE,
            role=None,
            content=None,
            tool_name="bash",
            tool_input={"command": "pwd"},
            tool_output=None,
            tokens=None,
            duration_ms=None,
            model_used="codex/gpt-5.4",
            agent_id="persona",
            agent_name="persona",
            created_at=now,
        ),
        SimpleNamespace(
            id="evt-tool-2",
            turn=8,
            sequence=3,
            event_type=SessionEventType.TOOL_RESULT,
            role=None,
            content="ok",
            tool_name="bash",
            tool_input=None,
            tool_output={"content": "ok", "is_error": False},
            tokens=None,
            duration_ms=10,
            model_used="codex/gpt-5.4",
            agent_id="persona",
            agent_name="persona",
            created_at=now,
        ),
        SimpleNamespace(
            id="evt-assistant",
            turn=8,
            sequence=4,
            event_type=SessionEventType.ASSISTANT_MESSAGE,
            role="assistant",
            content="done",
            tool_name=None,
            tool_input=None,
            tool_output=None,
            tokens=12,
            duration_ms=None,
            model_used="codex/gpt-5.4",
            agent_id="persona",
            agent_name="persona",
            created_at=now,
        ),
    ]

    messages = convert_messages_to_response(events, agent_display_names={"persona": "Jenny"})

    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].content == "done"
    assert messages[1].tool_executions is not None
    assert len(messages[1].tool_executions) == 1
