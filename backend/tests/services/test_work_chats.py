from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import (
    AgentBenchmarkAttempt,
    AgentBenchmarkRun,
    AgentPerformanceLog,
    SessionEventType,
)
from app.services.event_storage import store_child_session_lifecycle_event
from app.services.work_chat_verifier_outcomes import record_verifier_outcome


@pytest.mark.asyncio
async def test_child_session_lifecycle_event_is_stored_on_parent_with_source_metadata() -> None:
    child = SimpleNamespace(
        id="child-session",
        parent_session_id="parent-session",
        status="active",
        agent_slug="coder",
        project_id="summitflow",
        external_id="task-123",
        summary_oneliner="editing files",
        workstream_status=None,
        current_branch="task-123/main",
        observed_write_paths=["frontend/src/app/work-chats/page.tsx"],
        provider_metadata={
            "source_metadata": {
                "transport": "web",
                "surface": "work_chats",
                "pane_id": "pane-1",
                "source_client": "agent-hub/work-chats",
            }
        },
    )

    with patch("app.services.event_storage.store_event", new_callable=AsyncMock) as mock_store:
        await store_child_session_lifecycle_event(
            AsyncMock(),
            child,
            SessionEventType.CHILD_SESSION_STARTED,
        )

    mock_store.assert_awaited_once()
    store_args = mock_store.await_args
    assert store_args is not None
    kwargs = store_args.kwargs
    assert kwargs["session_id"] == "parent-session"
    assert kwargs["event_type"] == SessionEventType.CHILD_SESSION_STARTED
    assert kwargs["pane_id"] == "pane-1"
    assert kwargs["surface"] == "work_chats"
    assert kwargs["source_client"] == "agent-hub/work-chats"
    assert kwargs["tool_output"]["child_session_id"] == "child-session"
    assert kwargs["tool_output"]["observed_write_paths"] == [
        "frontend/src/app/work-chats/page.tsx"
    ]


@pytest.mark.asyncio
async def test_record_verifier_outcome_persists_performance_and_benchmark_signal() -> None:
    builder = SimpleNamespace(
        id="builder-session",
        agent_slug="coder",
        project_id="summitflow",
        model="codex/gpt-5.5",
        models_used=["codex/gpt-5.5"],
        provider="codex",
        providers_used=["codex"],
        request_source="summitflow-frontend",
        client_id="client-1",
    )
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(side_effect=[None, builder])
    cost_result = MagicMock()
    cost_result.one_or_none.return_value = SimpleNamespace(input_tokens=120, output_tokens=30)
    db.execute = AsyncMock(return_value=cost_result)

    async def flush() -> None:
        for call in db.add.call_args_list:
            obj = call.args[0]
            if isinstance(obj, AgentPerformanceLog):
                obj.id = 7
            if isinstance(obj, AgentBenchmarkRun):
                obj.id = "run-1"

    db.flush = AsyncMock(side_effect=flush)

    result = await record_verifier_outcome(
        db,
        {
            "parent_session_id": "parent-session",
            "verifier_session_id": "verifier-session",
            "builder_session_id": "builder-session",
            "project_id": "summitflow",
            "task_id": "task-123",
            "status": "verified",
            "confidence": "VERIFIED",
            "atomic_claim_count": 4,
            "atomic_pass_count": 3,
            "atomic_fail_count": 1,
            "feedback_loop_count": 1,
            "report_excerpt": "Three claims passed; one minor doc claim failed.",
        },
    )

    added = [call.args[0] for call in db.add.call_args_list]
    performance_log = next(obj for obj in added if isinstance(obj, AgentPerformanceLog))
    benchmark_run = next(obj for obj in added if isinstance(obj, AgentBenchmarkRun))
    benchmark_attempt = next(obj for obj in added if isinstance(obj, AgentBenchmarkAttempt))

    assert result.created is True
    assert result.agent_slug == "coder"
    assert result.score == 86
    assert performance_log.feedback_type == "praise"
    assert performance_log.outcome == "success"
    assert performance_log.input_tokens == 120
    assert benchmark_run.suite_id == "work-chats-verifier"
    assert benchmark_run.run_kind == "verifier_outcome"
    assert benchmark_run.avg_score == 86
    assert benchmark_run.run_metadata["atomic_fail_count"] == 1
    assert benchmark_attempt.session_id == "builder-session"
    assert benchmark_attempt.composite_score == 86
