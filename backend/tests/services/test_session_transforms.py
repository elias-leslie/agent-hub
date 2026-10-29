"""Focused tests for session response/list transformations."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

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


def test_native_model_response_uses_current_evidence_instead_of_stale_routing() -> None:
    evidence = {
        "session_id": "sess-1", "native_session_id": "root", "turn_id": "current",
        "source": "codex_transcript", "source_path": "/tmp/native.jsonl",
        "source_generation": "generation", "source_line": 17,
        "source_timestamp": "2026-09-30T15:00:00Z",
        "requested_model": "gpt-6.1-sol", "requested_reasoning_effort": "high",
        "observed_model": None,
    }
    session = _session(provider_metadata={
        "transcript_path": "/tmp/native.jsonl", "model_evidence": evidence,
        "requested_model": "codex/stale", "effective_model": "codex/stale",
        "transcript_ingestion": {"source_health": {"source_generation": "generation"}},
    })
    for response in (build_session_response(session), build_session_list_items([session], {}, {})[0]):
        assert response.requested_model == "codex/gpt-6.1-sol"
        assert response.model == response.effective_model == "codex/unknown"
        assert response.model_evidence is not None
        assert response.model_evidence.turn_id == "current"
        assert response.model_evidence.requested_reasoning_effort == "high"
        assert response.model_evidence.observed_model is None
        assert response.fallback_used is False
    assert session.provider_metadata is not None
    session.provider_metadata["model_evidence"]["observed_model"] = "served-alias"
    session.provider_metadata["model_evidence"]["observed_source"] = "codex.response_item.model"
    session.provider_metadata["model_evidence"]["observed_source_line"] = 19
    session.provider_metadata["model_evidence"]["observed_source_timestamp"] = "2026-09-30T15:01:00Z"
    response = build_session_response(session)
    assert response.model == "codex/served-alias"
    assert response.fallback_used is False
    # A copied child or another source generation cannot supply delivery evidence.
    session.provider_metadata["model_evidence"]["session_id"] = "other"
    response = build_session_response(session)
    assert response.model == "codex/unknown"
    assert response.model_evidence is None


def test_native_model_without_provenance_is_unknown() -> None:
    session = _session(provider_metadata={"transcript_path": "/tmp/native.jsonl", "effective_model": "codex/stale"})
    response = build_session_response(session)
    assert response.model == response.requested_model == "codex/unknown"
    assert response.model_evidence is None


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
        request_source="manual/network-baseline",
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "source_client": "summitflow",
            "session_kind": "benchmark",
        },
    )

    item = build_session_list_items([session], {}, {})[0]

    assert item.attribution_kind == "benchmark"
    assert item.attribution_label == "Benchmark"
    assert item.attribution_detail == "manual/network-baseline"


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

    messages = convert_messages_to_response(events, agent_display_names={"persona": "Worker Agent"})

    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].agent_display_name == "Worker Agent"
    assert messages[0].content == "Tool activity recorded without a final assistant summary. Tools: bash."
    assert messages[0].tool_executions is not None
    assert len(messages[0].tool_executions) == 1
    assert messages[0].tool_executions[0].name == "bash"
    assert messages[0].tool_executions[0].result == "Created checkout"
    assert messages[0].kind == "incomplete_turn"


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

    messages = convert_messages_to_response(events, agent_display_names={"persona": "Worker Agent"})

    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].content == "done"
    assert messages[1].tool_executions is not None
    assert len(messages[1].tool_executions) == 1


def _fully_populated_session() -> Session:
    evidence = {
        "session_id": "sess-1", "native_session_id": "root", "turn_id": "turn-9",
        "source": "codex_transcript", "source_path": "/tmp/native.jsonl",
        "source_generation": "generation", "source_line": 17,
        "source_timestamp": "2026-09-30T15:00:00Z",
        "requested_model": "gpt-6.1-sol", "requested_reasoning_effort": "high",
        "observed_model": "served-alias", "observed_source": "codex.response_item.model",
        "observed_source_line": 19, "observed_source_timestamp": "2026-09-30T15:01:00Z",
    }
    return _session(
        status="active",
        agent_slug="ops-agent",
        parent_session_id="sess-parent",
        external_id="task-123",
        client_id="client-1",
        request_source="summitflow",
        current_branch="main",
        workstream_status="active",
        summary_oneliner="Refactoring session fields",
        declared_scope_paths=["backend/app/api"],
        observed_read_paths=["backend/app/services/session_transforms.py", ""],
        observed_write_paths=["backend/app/api/schemas/sessions.py"],
        scope_confidence="unknown",
        provider_metadata={
            "repo_root": "/srv/workspaces/projects/agent-hub",
            "working_dir": "/srv/workspaces/projects/agent-hub/backend",
            "host": "davion-sidarli",
            "tmux_session_name": "aico-1",
            "tmux_pane_id": "%3",
            "source_client": "summitflow",
            "source_path": "backend/app/worker.py",
            "batch_task_ids": ["task-a", " task-b ", "", 7],
            "transcript_path": "/tmp/native.jsonl",
            "model_evidence": evidence,
            "transcript_ingestion": {"source_health": {"source_generation": "generation"}},
            "external_identity": {"harness": "codex", "launcher": "aico"},
            "live_activity": {
                "phase": "error",
                "status": "error",
                "last_event_at": "2026-01-01T00:00:00Z",
                "last_tool_name": "Bash",
            },
        },
    )


def _without_clock_fields(payload: dict[str, Any]) -> dict[str, Any]:
    live_activity = payload.get("live_activity")
    if isinstance(live_activity, dict):
        payload["live_activity"] = {
            key: value for key, value in live_activity.items() if key != "quiet_for_seconds"
        }
    return payload


def test_list_item_and_response_agree_on_every_shared_field() -> None:
    session = _fully_populated_session()

    item = build_session_list_items(
        [session],
        {"sess-1": 4},
        {"sess-1": {"input": 120, "output": 30}},
        event_counts={"sess-1": 9},
        child_counts={"sess-1": 3},
        active_child_counts={"sess-1": 1},
        owner_session_ids={"sess-1"},
        specialist_session_ids=set(),
    )[0]
    response = build_session_response(
        session,
        total_input=120,
        total_output=30,
        message_count=4,
        event_count=9,
        child_session_count=3,
        active_child_session_count=1,
        owner_session_ids={"sess-1"},
        specialist_session_ids=set(),
    )

    item_payload = _without_clock_fields(item.model_dump(mode="json"))
    response_payload = _without_clock_fields(response.model_dump(mode="json"))
    assert set(item_payload) - set(response_payload) == set()
    assert set(response_payload) - set(item_payload) == {
        "messages",
        "context_usage",
        "agent_token_breakdown",
    }
    assert {key: response_payload[key] for key in item_payload} == item_payload
    # Every shared field is populated, so the parity check covers real values.
    assert item_payload["agent_slug"] == "ops-agent"
    assert item_payload["model_evidence"] is not None
    assert item_payload["external_identity"] == {
        "harness": "codex", "launcher": "aico", "display_identity": None,
        "runtime_session_id": None, "agent_path": None, "aico_session_id": None,
        "aico_widget_id": None, "aico_project_id": None, "project_mapping_state": None,
    }
    assert item_payload["batch_task_ids"] == ["task-a", "task-b"]
    assert item_payload["observed_read_paths"] == ["backend/app/services/session_transforms.py"]
    assert item_payload["scope_confidence"] == "declared"
    assert item_payload["host"] == "davion-sidarli"
    assert item_payload["working_dir"] == "/srv/workspaces/projects/agent-hub/backend"
    assert item_payload["attribution_kind"] == "autonomous"
    assert item_payload["status_source"] == "runtime"
    assert item_payload["status_matches_live"] is False
    assert item_payload["live_activity"]["has_owner_lane"] is True
    assert item_payload["child_session_count"] == 3
    assert item_payload["total_input_tokens"] == 120


def test_list_item_and_response_defaults_for_missing_counts_differ_as_documented() -> None:
    session = _session()

    item = build_session_list_items([session], {}, {})[0]
    response = build_session_response(session)

    assert (item.message_count, item.event_count) == (0, 0)
    assert (response.message_count, response.event_count) == (None, None)
    assert item.child_session_count is None
    assert response.child_session_count is None


def test_session_list_item_and_response_schemas_share_field_definitions() -> None:
    from app.api.schemas.sessions import SessionListItem, SessionResponse

    list_schema = SessionListItem.model_json_schema()
    detail_schema = SessionResponse.model_json_schema()
    list_props = list_schema["properties"]
    detail_props = detail_schema["properties"]

    assert set(detail_props) - set(list_props) == {
        "messages",
        "context_usage",
        "agent_token_breakdown",
    }
    assert set(list_props) <= set(detail_props)
    differing = {
        name for name in list_props if list_props[name] != detail_props[name]
    }
    assert differing == {"message_count", "status_source"}
    assert set(list_schema["required"]) == {
        "id", "project_id", "provider", "model", "status",
        "message_count", "created_at", "updated_at",
    }
    assert set(detail_schema["required"]) == {
        "id", "project_id", "provider", "model", "status",
        "created_at", "updated_at",
    }
    assert list_props["message_count"] == {"title": "Message Count", "type": "integer"}
    assert detail_props["message_count"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
    assert detail_props["message_count"]["default"] is None
    assert list_props["status_source"]["description"] == (
        "Authority for row status beacon: session or runtime"
    )
    assert detail_props["status_source"]["description"] == (
        "Authority for row/detail status beacon: session or runtime"
    )


def test_session_summary_kwargs_only_names_shared_schema_fields() -> None:
    # Both models ignore unknown kwargs, so a misspelled helper key would silently fall back to
    # the field default; pin every helper key to a declared shared field.
    from app.api.schemas.sessions import SessionSummaryFields
    from app.services.session_transforms import _session_summary_kwargs

    for session in (_session(), _fully_populated_session()):
        kwargs = _session_summary_kwargs(session, owner_session_ids=None, specialist_session_ids=None)
        assert set(kwargs) <= set(SessionSummaryFields.model_fields)


def _event(seq: int, event_type: str, **fields: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": f"evt-{seq}", "turn": 1, "sequence": seq, "event_type": event_type, "role": None, "content": None,
        "tool_name": None, "call_id": None, "tool_input": None, "tool_output": None, "tokens": None,
        "duration_ms": None, "model_used": "m", "agent_id": "chat", "agent_name": "chat",
        "created_at": datetime.now(UTC),
    }
    base.update(fields)
    return SimpleNamespace(**base)


def test_a_chat_session_keeps_each_exchanges_thinking_and_tools_with_its_own_answer() -> None:
    """A chat session numbers every event as turn 1; the second answer must not inherit the first's trace."""
    events = [
        _event(1, SessionEventType.USER_MESSAGE, role="user", content="read a"),
        _event(2, SessionEventType.THINKING, content="first thought", tokens=5),
        _event(3, SessionEventType.TOOL_USE, tool_name="read", call_id="c1", tool_input={"path": "a"}),
        _event(4, SessionEventType.TOOL_RESULT, tool_name="read", call_id="c1",
               tool_output={"content": "alpha", "is_error": False}, content="alpha"),
        _event(5, SessionEventType.ASSISTANT_MESSAGE, role="assistant", content="a says alpha"),
        _event(6, SessionEventType.USER_MESSAGE, role="user", content="and now"),
        _event(7, SessionEventType.ASSISTANT_MESSAGE, role="assistant", content="nothing more"),
    ]

    messages = convert_messages_to_response(events)

    assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[1].thinking == "first thought"
    assert messages[1].thinking_tokens == 5
    assert [t.name for t in messages[1].tool_executions or []] == ["read"]
    assert messages[3].thinking is None
    assert not messages[3].tool_executions


def test_tool_results_match_their_own_call_and_come_back_as_bounded_text() -> None:
    from app.services.event_storage import TOOL_RESULT_SUMMARY_CHARS

    big = "y" * (TOOL_RESULT_SUMMARY_CHARS + 50)
    events = [
        _event(1, SessionEventType.TOOL_USE, tool_name="read", call_id="c1", tool_input={"path": "a"}),
        _event(2, SessionEventType.TOOL_USE, tool_name="read", call_id="c2", tool_input={"path": "b"}),
        _event(3, SessionEventType.TOOL_RESULT, tool_name="read", call_id="c2",
               tool_output={"content": "denied", "is_error": True}, content="denied"),
        _event(4, SessionEventType.TOOL_RESULT, tool_name="read", call_id="c1", tool_output={"text": big}),
        _event(5, SessionEventType.ASSISTANT_MESSAGE, role="assistant", content="ok"),
    ]

    tools = convert_messages_to_response(events)[0].tool_executions or []

    assert [(t.status, t.result) for t in tools] == [
        ("complete", "y" * TOOL_RESULT_SUMMARY_CHARS + "…"),
        ("error", "denied"),
    ]


def test_results_without_call_ids_pair_with_the_first_unanswered_call_of_that_name() -> None:
    events = [
        _event(1, SessionEventType.TOOL_USE, tool_name="bash", tool_input={"command": "pwd"}),
        _event(2, SessionEventType.TOOL_USE, tool_name="bash", tool_input={"command": "ls"}),
        _event(3, SessionEventType.TOOL_RESULT, tool_name="bash", tool_output={"text": "/srv"}),
        _event(4, SessionEventType.TOOL_RESULT, tool_name="bash", tool_output={"text": "a b"}),
        _event(5, SessionEventType.ASSISTANT_MESSAGE, role="assistant", content="ok"),
    ]

    tools = convert_messages_to_response(events)[0].tool_executions or []

    assert [t.result for t in tools] == ["/srv", "a b"]


def test_a_reopened_answer_carries_where_each_tool_call_happened_and_how_long_it_thought() -> None:
    events = [
        _event(1, SessionEventType.USER_MESSAGE, role="user", content="fix"),
        _event(2, SessionEventType.THINKING, content="plan", duration_ms=2500),
        _event(3, SessionEventType.TOOL_USE, tool_name="read", call_id="c1", content_offset=11),
        _event(4, SessionEventType.TOOL_RESULT, tool_name="read", call_id="c1", content="alpha"),
        _event(5, SessionEventType.TOOL_USE, tool_name="edit", call_id="c2", content_offset=19),
        _event(6, SessionEventType.TOOL_RESULT, tool_name="edit", call_id="c2", content="done"),
        _event(7, SessionEventType.ASSISTANT_MESSAGE, role="assistant", content="Looking... Fixing. Fixed."),
    ]

    answer = convert_messages_to_response(events)[1]

    assert [(t.name, t.content_offset) for t in answer.tool_executions] == [("read", 11), ("edit", 19)]
    assert answer.thinking_ms == 2500


def test_an_old_answer_without_recorded_offsets_or_thinking_time_says_so() -> None:
    events = [
        _event(1, SessionEventType.TOOL_USE, tool_name="read", call_id="c1"),
        _event(2, SessionEventType.ASSISTANT_MESSAGE, role="assistant", content="ok"),
    ]

    answer = convert_messages_to_response(events)[0]

    assert [t.content_offset for t in answer.tool_executions] == [None]
    assert answer.thinking_ms is None


def test_a_compaction_comes_back_as_a_marked_line_between_the_messages_it_fell_among() -> None:
    record = {"status": "ok", "tokens_before": 9200, "tokens_after": 6400, "summarizer_model": "m", "cost_usd": 0.01}
    events = [
        _event(1, SessionEventType.USER_MESSAGE, role="user", content="go"),
        _event(2, SessionEventType.COMPACTION, content="Context compacted: 9200 -> 6400 tokens", tool_output=record),
        _event(3, SessionEventType.ASSISTANT_MESSAGE, role="assistant", content="done"),
    ]

    messages = convert_messages_to_response(events)

    assert [(m.role, m.kind) for m in messages] == [("user", None), ("system", "compaction"), ("assistant", None)]
    assert messages[1].compaction == record
    assert messages[1].tokens == 0
