"""Tests for agent wake prompt shaping and summary post-processing."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from app.workflows.persona_wake import WakeInput, _build_wake_prompt, agent_wake_task


def _mock_async_session(mock_db):
    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session


def _mock_execute_result(value):
    return SimpleNamespace(scalar_one_or_none=lambda: value)


def assert_prompt_contains_all(prompt: str, substrings: list[str]) -> None:
    for substring in substrings:
        assert substring in prompt, f"Expected prompt to contain: {substring!r}"


def _await_kwargs(mock: AsyncMock) -> dict[str, Any]:
    await_args = mock.await_args
    assert await_args is not None
    return dict(await_args.kwargs)


@pytest.mark.asyncio
async def test_build_wake_prompt_includes_current_st_guidance():
    guidance = "\n".join(
        [
            "st ready-all",
            "st ready --limit N",
            "st sessions list --status <status> --limit N",
            "st session-events <session_id>",
            "st session-events -T task-123 --page-size 100",
            "Do not add stale flags like `-P`, `--project`, `--human`, or `--compact`",
            "Do not use `--session` with `st session-events`",
            "Never pass `st sessions list` output `session_id` values to `st session-events`",
            "Only use `st session-events <session_id>` when you already have a real Agent Hub session UUID",
            "If `st session-events -T task-...` reports no linked Agent Hub sessions, treat that as evidence and move on",
            "do not inspect `/home/testuser//.local/share/st/checkpoints/...`",
            "If a snapshot metadata file includes a `working_dir` outside the current repo root, treat it as metadata only",
            "Treat task ids as opaque",
            "do not strip the `task-` prefix",
            "Example: `st done <task-id>` has no `--note` flag",
            "start with the concrete task context, current diff/status, and the files or commands named in the task/prompt",
            "inspect those first and only widen the search if that targeted path is insufficient",
            "Prefer `dt -q -d` as the first validation pass from the repo root",
            "use paths relative to that directory",
            "For `read_file`, use repo-relative paths or fully expanded absolute paths",
            "Do not use shell shortcuts like `~` inside `read_file` paths",
            "If a direct path inspection is denied by tool policy, treat that denial as a real boundary",
            "If `git branch` or snapshot metadata shows a task branch already attached to another checkout",
            "Do not `git checkout` that branch in the current checkout just to inspect it",
            "Use `git show`, `git log`, and `git diff` against the branch name from the current repo instead",
            'When completing a task with a note, use `st done <task-id> --message "..."`',
            "Avoid exploratory `--help` calls unless a known-good command above still fails.",
        ]
    )
    with patch(
        "app.services.persona_prompt_service.get_persona_wake_guidance",
        new=AsyncMock(return_value=guidance),
    ):
        prompt = await _build_wake_prompt("Investigate the current task branch.")

    assert_prompt_contains_all(
        prompt,
        [
            "st ready-all",
            "st ready --limit N",
            "st sessions list --status <status> --limit N",
            "st session-events <session_id>",
            "st session-events -T task-123 --page-size 100",
            "Do not add stale flags like `-P`, `--project`, `--human`, or `--compact`",
            "Do not use `--session` with `st session-events`",
            "Never pass `st sessions list` output `session_id` values to `st session-events`",
            "Only use `st session-events <session_id>` when you already have a real Agent Hub session UUID",
            "If `st session-events -T task-...` reports no linked Agent Hub sessions, treat that as evidence and move on",
            "do not inspect `/home/testuser//.local/share/st/checkpoints/...`",
            "If a snapshot metadata file includes a `working_dir` outside the current repo root, treat it as metadata only",
            "Treat task ids as opaque",
            "do not strip the `task-` prefix",
            "Example: `st done <task-id>` has no `--note` flag",
            "start with the concrete task context, current diff/status, and the files or commands named in the task/prompt",
            "inspect those first and only widen the search if that targeted path is insufficient",
            "Prefer `dt -q -d` as the first validation pass from the repo root",
            "use paths relative to that directory",
            "For `read_file`, use repo-relative paths or fully expanded absolute paths",
            "Do not use shell shortcuts like `~` inside `read_file` paths",
            "If a direct path inspection is denied by tool policy, treat that denial as a real boundary",
            "If `git branch` or snapshot metadata shows a task branch already attached to another checkout",
            "Do not `git checkout` that branch in the current checkout just to inspect it",
            "Use `git show`, `git log`, and `git diff` against the branch name from the current repo instead",
            'When completing a task with a note, use `st done <task-id> --message "..."`',
            "Avoid exploratory `--help` calls unless a known-good command above still fails.",
            "Task:\nInvestigate the current task branch.",
        ],
    )


@pytest.mark.asyncio
async def test_agent_wake_stores_summary_for_completed_session():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_mock_execute_result(None))
    complete_result = SimpleNamespace(
        status="success",
        turns=4,
        tool_calls_count=3,
        error=None,
        session_id="sess-wake-1",
        content="Investigated checkout and found valid in-progress work.",
    )
    mock_perm = SimpleNamespace(permission_tier="full")
    mock_persona = SimpleNamespace(limits=None)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.persona_prompt_service.get_persona_wake_guidance",
            new=AsyncMock(return_value="Wake guidance\nst ready-all"),
        ),
        patch(
            "app.services.project_permission_service.get_project_permission",
            new_callable=AsyncMock,
            return_value=mock_perm,
        ),
        patch(
            "app.services.persona_service.get_persona",
            new_callable=AsyncMock,
            return_value=mock_persona,
        ),
        patch(
            "app.services._persona_crud.get_persona_limit",
            return_value=500,
        ),
        patch(
            "app.api.complete.core.complete_internal",
            new_callable=AsyncMock,
            return_value=complete_result,
        ) as mock_complete,
        patch(
            "app.workflows.persona_wake.ensure_session_summary",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_summary,
        patch(
            "app.workflows.persona_wake.log_agent_performance",
            new_callable=AsyncMock,
        ) as mock_perf,
    ):
        result = await agent_wake_task.aio_mock_run(
            WakeInput(
                agent_slug="debugger",
                model="codex/gpt-5.4",
                provider="codex",
                prompt="Inspect the dirty checkout and decide if it is valid progress.",
                project_id="a-term",
                event_type="dispatch",
                thinking_level="medium",
                max_turns=25,
            )
        )

    assert result["summary_stored"] is True
    mock_perf.assert_awaited_once()
    perf_kwargs = _await_kwargs(mock_perf)
    assert "missing inline [[S:...]] summary tag" in str(perf_kwargs["content"])
    mock_summary.assert_awaited_once_with(
        "sess-wake-1",
        "Investigated checkout and found valid in-progress work.",
        agent_id="debugger",
    )
    complete_kwargs = _await_kwargs(mock_complete)
    messages = cast(list[dict[str, Any]], complete_kwargs["messages"])
    assert len(messages) == 1
    assert "st ready-all" in messages[0]["content"]
    assert "Task:\nInspect the dirty checkout" in messages[0]["content"]
    assert complete_kwargs["external_id"] == "wake-step:mock-step-run-id"
    assert complete_kwargs["request_source"] == "persona_wake:dispatch"


@pytest.mark.asyncio
async def test_agent_wake_forwards_parent_session_id():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_mock_execute_result(None))
    complete_result = SimpleNamespace(
        status="success",
        turns=2,
        tool_calls_count=1,
        error=None,
        session_id="sess-wake-2",
        content="Recovered stale task state.",
    )
    mock_perm = SimpleNamespace(permission_tier="full")
    mock_persona = SimpleNamespace(limits=None)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.persona_prompt_service.get_persona_wake_guidance",
            new=AsyncMock(return_value="Wake guidance\nst ready-all"),
        ),
        patch(
            "app.services.project_permission_service.get_project_permission",
            new_callable=AsyncMock,
            return_value=mock_perm,
        ),
        patch(
            "app.services.persona_service.get_persona",
            new_callable=AsyncMock,
            return_value=mock_persona,
        ),
        patch("app.services._persona_crud.get_persona_limit", return_value=500),
        patch(
            "app.api.complete.core.complete_internal",
            new_callable=AsyncMock,
            return_value=complete_result,
        ) as mock_complete,
        patch(
            "app.workflows.persona_wake.ensure_session_summary",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.workflows.persona_wake.log_agent_performance",
            new_callable=AsyncMock,
        ),
        ):
            await agent_wake_task.aio_mock_run(
            WakeInput(
                agent_slug="debugger",
                model="codex/gpt-5.4",
                provider="codex",
                prompt="Advance recovery.",
                project_id="summitflow",
                event_type="dispatch",
                parent_session_id="parent-session-456",
            )
        )

    complete_kwargs = _await_kwargs(mock_complete)
    assert complete_kwargs["parent_session_id"] == "parent-session-456"


@pytest.mark.asyncio
async def test_agent_wake_forwards_lane_metadata():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_mock_execute_result(None))
    complete_result = SimpleNamespace(
        status="success",
        turns=2,
        tool_calls_count=1,
        error=None,
        session_id="sess-wake-3",
        content="Finished task-lane validation.",
    )
    mock_perm = SimpleNamespace(permission_tier="full")
    mock_persona = SimpleNamespace(limits=None)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.persona_prompt_service.get_persona_wake_guidance",
            new=AsyncMock(return_value="Wake guidance\nst ready-all"),
        ),
        patch(
            "app.services.project_permission_service.get_project_permission",
            new_callable=AsyncMock,
            return_value=mock_perm,
        ),
        patch(
            "app.services.persona_service.get_persona",
            new_callable=AsyncMock,
            return_value=mock_persona,
        ),
        patch("app.services._persona_crud.get_persona_limit", return_value=500),
        patch(
            "app.api.complete.core.complete_internal",
            new_callable=AsyncMock,
            return_value=complete_result,
        ) as mock_complete,
        patch(
            "app.workflows.persona_wake.ensure_session_summary",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.workflows.persona_wake.log_agent_performance",
            new_callable=AsyncMock,
        ),
        ):
            await agent_wake_task.aio_mock_run(
            WakeInput(
                agent_slug="refactor",
                model="codex/gpt-5.4",
                provider="codex",
                prompt="Mode: task\nTask-ID: task-12345678\nTask: Refactor the overlap preflight.",
                project_id="agent-hub",
                event_type="dispatch_task",
                current_branch="task-12345678/main",
                working_dir="/tmp/lanes/task-12345678",
            )
        )

    complete_kwargs = _await_kwargs(mock_complete)
    assert complete_kwargs["external_id"] == "wake-step:mock-step-run-id"
    assert complete_kwargs["current_branch"] == "task-12345678/main"
    assert complete_kwargs["working_dir"] == "/tmp/lanes/task-12345678"
    assert complete_kwargs["request_source"] == "persona_wake:dispatch_task"


@pytest.mark.asyncio
async def test_agent_wake_falls_back_to_project_root_when_working_dir_missing():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_mock_execute_result(None))
    complete_result = SimpleNamespace(
        status="success",
        turns=2,
        tool_calls_count=1,
        error=None,
        session_id="sess-wake-4",
        content="Closed the task from the project root.",
    )
    mock_perm = SimpleNamespace(permission_tier="full")
    mock_persona = SimpleNamespace(limits=None)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.persona_prompt_service.get_persona_wake_guidance",
            new=AsyncMock(return_value="Wake guidance\nst ready-all"),
        ),
        patch(
            "app.services.project_permission_service.get_project_permission",
            new_callable=AsyncMock,
            return_value=mock_perm,
        ),
        patch(
            "app.services.persona_service.get_persona",
            new_callable=AsyncMock,
            return_value=mock_persona,
        ),
        patch("app.services._persona_crud.get_persona_limit", return_value=500),
        patch(
            "app.api.complete.core.complete_internal",
            new_callable=AsyncMock,
            return_value=complete_result,
        ) as mock_complete,
        patch(
            "app.workflows.persona_wake.ensure_session_summary",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.workflows.persona_wake.log_agent_performance",
            new_callable=AsyncMock,
        ),
        patch(
            "app.workflows.persona_wake._resolve_wake_working_dir",
            return_value="/srv/workspaces/projects/agent-hub",
        ) as mock_resolve,
    ):
        await agent_wake_task.aio_mock_run(
            WakeInput(
                agent_slug="persona",
                model="codex/gpt-5.4",
                provider="codex",
                prompt="Close out task-22b3fdea cleanly.",
                project_id="agent-hub",
                event_type="autocode_complete",
                task_id="task-22b3fdea",
            )
        )

    mock_resolve.assert_called_once_with("agent-hub", None)
    complete_kwargs = _await_kwargs(mock_complete)
    assert complete_kwargs["working_dir"] == "/srv/workspaces/projects/agent-hub"


@pytest.mark.asyncio
async def test_agent_wake_skips_replayed_step_run() -> None:
    existing = SimpleNamespace(
        id="existing-wake-session",
        summary_oneliner=None,
        summary_generated_at=None,
    )
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_mock_execute_result(existing))
    mock_perm = SimpleNamespace(permission_tier="full")

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.persona_prompt_service.get_persona_wake_guidance",
            new=AsyncMock(return_value="Wake guidance\nst ready-all"),
        ),
        patch(
            "app.services.project_permission_service.get_project_permission",
            new_callable=AsyncMock,
            return_value=mock_perm,
        ),
        patch(
            "app.workflows.persona_wake._wake_external_id",
            return_value="wake-step:replayed",
        ),
        patch(
            "app.api.complete.core.complete_internal",
            new_callable=AsyncMock,
        ) as mock_complete,
        patch(
            "app.workflows.persona_wake.ensure_session_summary",
            new_callable=AsyncMock,
        ) as mock_summary,
        patch(
            "app.workflows.persona_wake.log_agent_performance",
            new_callable=AsyncMock,
        ) as mock_perf,
    ):
        result = await agent_wake_task.aio_mock_run(
            WakeInput(
                agent_slug="debugger",
                model="codex/gpt-5.4",
                provider="codex",
                prompt="Advance recovery.",
                project_id="summitflow",
                event_type="dispatch",
            )
        )

    assert result["status"] == "skipped"
    assert result["error"] == "duplicate_step_run:existing-wake-session"
    mock_complete.assert_not_awaited()
    mock_summary.assert_not_awaited()
    mock_perf.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_wake_logs_missing_progress_tags_for_task_session() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_mock_execute_result(None))
    complete_result = SimpleNamespace(
        status="success",
        turns=3,
        tool_calls_count=2,
        error=None,
        session_id="sess-wake-tags-1",
        content="Implemented the lane fix.",
    )
    mock_perm = SimpleNamespace(permission_tier="full")
    mock_persona = SimpleNamespace(limits=None)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.persona_prompt_service.get_persona_wake_guidance",
            new=AsyncMock(return_value="Wake guidance\nst ready-all"),
        ),
        patch(
            "app.services.project_permission_service.get_project_permission",
            new_callable=AsyncMock,
            return_value=mock_perm,
        ),
        patch(
            "app.services.persona_service.get_persona",
            new_callable=AsyncMock,
            return_value=mock_persona,
        ),
        patch("app.services._persona_crud.get_persona_limit", return_value=500),
        patch(
            "app.api.complete.core.complete_internal",
            new_callable=AsyncMock,
            return_value=complete_result,
        ),
        patch(
            "app.workflows.persona_wake.ensure_session_summary",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.workflows.persona_wake.log_agent_performance",
            new_callable=AsyncMock,
        ) as mock_perf,
    ):
        await agent_wake_task.aio_mock_run(
            WakeInput(
                agent_slug="coder",
                model="codex/gpt-5.4",
                provider="codex",
                prompt="Implement the scoped task.",
                project_id="agent-hub",
                event_type="dispatch_task",
                task_id="task-12345678",
            )
        )

    assert mock_perf.await_count == 1
    perf_kwargs = _await_kwargs(mock_perf)
    content = str(perf_kwargs["content"])
    assert "missing inline [[S:...]] summary tag" in content
    assert "missing [[P:...]] progress tags on task session" in content


@pytest.mark.asyncio
async def test_agent_wake_skips_tag_gap_log_when_both_tags_present() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_mock_execute_result(None))
    complete_result = SimpleNamespace(
        status="success",
        turns=3,
        tool_calls_count=2,
        error=None,
        session_id="sess-wake-tags-2",
        content=(
            "[[P:started:reading task context]]"
            "[[P:tested:dt -q -d passes clean]]"
            "[[S:completed:Validated the task checkpoint and finished the requested fix.]]"
        ),
    )
    mock_perm = SimpleNamespace(permission_tier="full")
    mock_persona = SimpleNamespace(limits=None)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.persona_prompt_service.get_persona_wake_guidance",
            new=AsyncMock(return_value="Wake guidance\nst ready-all"),
        ),
        patch(
            "app.services.project_permission_service.get_project_permission",
            new_callable=AsyncMock,
            return_value=mock_perm,
        ),
        patch(
            "app.services.persona_service.get_persona",
            new_callable=AsyncMock,
            return_value=mock_persona,
        ),
        patch("app.services._persona_crud.get_persona_limit", return_value=500),
        patch(
            "app.api.complete.core.complete_internal",
            new_callable=AsyncMock,
            return_value=complete_result,
        ),
        patch(
            "app.workflows.persona_wake.ensure_session_summary",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.workflows.persona_wake.log_agent_performance",
            new_callable=AsyncMock,
        ) as mock_perf,
    ):
        await agent_wake_task.aio_mock_run(
            WakeInput(
                agent_slug="coder",
                model="codex/gpt-5.4",
                provider="codex",
                prompt="Implement the scoped task.",
                project_id="agent-hub",
                event_type="dispatch_task",
                task_id="task-12345678",
            )
        )

    mock_perf.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_wake_rolls_back_and_closes_on_cancellation() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_mock_execute_result(None))
    mock_perm = SimpleNamespace(permission_tier="full")
    mock_persona = SimpleNamespace(limits=None)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.persona_prompt_service.get_persona_wake_guidance",
            new=AsyncMock(return_value="Wake guidance\nst ready-all"),
        ),
        patch(
            "app.services.project_permission_service.get_project_permission",
            new_callable=AsyncMock,
            return_value=mock_perm,
        ),
        patch(
            "app.services.persona_service.get_persona",
            new_callable=AsyncMock,
            return_value=mock_persona,
        ),
        patch("app.services._persona_crud.get_persona_limit", return_value=500),
        patch(
            "app.api.complete.core.complete_internal",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError,
        ),
        patch(
            "app.workflows.persona_wake._wake_external_id",
            return_value="wake-step:cancelled",
        ),pytest.raises(asyncio.CancelledError)
    ):
        await agent_wake_task.aio_mock_run(
            WakeInput(
                agent_slug="debugger",
                model="codex/gpt-5.4",
                provider="codex",
                prompt="Advance recovery.",
                project_id="summitflow",
                event_type="dispatch",
            )
        )

    mock_db.rollback.assert_awaited_once()
    mock_db.close.assert_awaited_once()
