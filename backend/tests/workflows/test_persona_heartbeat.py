"""Tests for persona heartbeat runtime compatibility and execution behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.models import CLAUDE_OPUS, CODEX_GPT_5_1_MINI, CODEX_GPT_5_4
from app.services.tools.direct_executor_core import KNOWN_ROOTS
from app.workflows.persona_heartbeat import (
    HEARTBEAT_MEMORY_GROUP,
    HEARTBEAT_PROJECT,
    HeartbeatInput,
    _build_runtime_warning,
    _do_completion,
    _run_persona_heartbeat,
    _should_run,
    get_heartbeat_runtime_info,
)


def _mock_async_session(mock_db):
    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session


class TestHeartbeatRuntimeInfo:
    """Tests for persona heartbeat runtime metadata."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("model_id", "provider"),
        [
            (CLAUDE_OPUS, "claude"),
            (CODEX_GPT_5_4, "codex"),
        ],
    )
    async def test_runtime_info_reports_supported_models(self, model_id, provider):
        mock_db = AsyncMock()
        resolved = (
            model_id,
            provider,
            0.7,
            "medium",
            "You are Jenny",
            None,
        )

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.workflows.persona_heartbeat._resolve_persona",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
        ):
            runtime = await get_heartbeat_runtime_info()

        assert runtime.model == model_id
        assert runtime.provider == provider
        assert runtime.supports_tools is True
        assert runtime.heartbeat_supported is True
        assert runtime.warnings == []

    @pytest.mark.asyncio
    async def test_runtime_info_warns_when_model_cannot_run_heartbeat_tools(self):
        mock_db = AsyncMock()
        resolved = (
            CODEX_GPT_5_1_MINI,
            "codex",
            0.7,
            "medium",
            "You are Jenny",
            None,
        )

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.workflows.persona_heartbeat._resolve_persona",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
        ):
            runtime = await get_heartbeat_runtime_info()

        assert runtime.supports_tools is False
        assert runtime.heartbeat_supported is False
        assert runtime.warnings == [_build_runtime_warning(CODEX_GPT_5_1_MINI)]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("model_id", "provider", "expected_supported"),
        [
            (CLAUDE_OPUS, "claude", True),
            (CODEX_GPT_5_4, "codex", True),
            (CODEX_GPT_5_1_MINI, "codex", False),
        ],
    )
    async def test_runtime_info_provider_comparison_uses_model_aware_capability_checks(
        self, model_id, provider, expected_supported
    ):
        mock_db = AsyncMock()

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.workflows.persona_heartbeat._resolve_persona",
                new_callable=AsyncMock,
                return_value=(model_id, provider, 0.7, "medium", "You are Jenny", None),
            ),
        ):
            runtime = await get_heartbeat_runtime_info()

        assert runtime.provider == provider
        assert runtime.supports_tools is expected_supported
        assert runtime.heartbeat_supported is expected_supported
        if expected_supported:
            assert runtime.warnings == []
        else:
            assert runtime.warnings == [_build_runtime_warning(model_id)]


class TestPersonaHeartbeatTask:
    """Tests for heartbeat task compatibility guardrails."""

    @pytest.mark.asyncio
    async def test_should_run_skips_when_persona_is_paused(self):
        with (
            patch(
                "app.workflows.persona_heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows.persona_heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="paused",
            ),
            patch(
                "app.workflows.persona_heartbeat.check_redis_elapsed",
                new_callable=AsyncMock,
            ) as mock_elapsed,
        ):
            result = await _should_run()

        assert result == (False, 60, True, "paused")
        mock_elapsed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manual_heartbeat_skips_when_runtime_is_incompatible(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows.persona_heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows.persona_heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.workflows.persona_heartbeat.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows.persona_heartbeat.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    model=CODEX_GPT_5_1_MINI,
                    heartbeat_supported=False,
                    warnings=[_build_runtime_warning(CODEX_GPT_5_1_MINI)],
                ),
            ),
            patch(
                "app.workflows.persona_heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
            ) as mock_set_running,
            patch(
                "app.workflows.persona_heartbeat._execute_heartbeat",
                new_callable=AsyncMock,
            ) as mock_execute,
        ):
            result = await _run_persona_heartbeat(HeartbeatInput(manual=True), ctx)

        assert result["status"] == "skipped"
        assert result["error"] == _build_runtime_warning(CODEX_GPT_5_1_MINI)
        mock_set_running.assert_not_awaited()
        mock_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manual_heartbeat_uses_model_name_from_runtime_when_warning_missing(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows.persona_heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows.persona_heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.workflows.persona_heartbeat.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows.persona_heartbeat.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    model="claude/unknown-no-tools",
                    heartbeat_supported=False,
                    warnings=[],
                ),
            ),
            patch(
                "app.workflows.persona_heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
            ) as mock_set_running,
            patch(
                "app.workflows.persona_heartbeat._execute_heartbeat",
                new_callable=AsyncMock,
            ) as mock_execute,
        ):
            result = await _run_persona_heartbeat(HeartbeatInput(manual=True), ctx)

        assert result["status"] == "skipped"
        assert result["error"] == _build_runtime_warning("claude/unknown-no-tools")
        mock_set_running.assert_not_awaited()
        mock_execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manual_heartbeat_skips_when_persona_is_paused(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows.persona_heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows.persona_heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="paused",
            ),
            patch(
                "app.workflows.persona_heartbeat.check_project_permission",
                new_callable=AsyncMock,
            ) as mock_permission,
            patch(
                "app.workflows.persona_heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
            ) as mock_set_running,
        ):
            result = await _run_persona_heartbeat(HeartbeatInput(manual=True), ctx)

        assert result["status"] == "skipped"
        mock_permission.assert_not_awaited()
        mock_set_running.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manual_heartbeat_runs_when_runtime_is_supported(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows.persona_heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows.persona_heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.workflows.persona_heartbeat.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows.persona_heartbeat.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    heartbeat_supported=True,
                    warnings=[],
                ),
            ),
            patch(
                "app.workflows.persona_heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workflows.persona_heartbeat.clear_heartbeat_running",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workflows.persona_heartbeat._execute_heartbeat",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    model_dump=lambda: {"status": "success", "turns": 3, "tool_calls": 2},
                    turns=3,
                    tool_calls=2,
                ),
            ) as mock_execute,
        ):
            result = await _run_persona_heartbeat(HeartbeatInput(manual=True), ctx)

        assert result["status"] == "success"
        mock_execute.assert_awaited_once_with(60, target_project_id=None)

    @pytest.mark.asyncio
    async def test_manual_heartbeat_passes_target_project_to_execution(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows.persona_heartbeat.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows.persona_heartbeat.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.workflows.persona_heartbeat.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_permission,
            patch(
                "app.workflows.persona_heartbeat.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    heartbeat_supported=True,
                    warnings=[],
                ),
            ),
            patch(
                "app.workflows.persona_heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workflows.persona_heartbeat.clear_heartbeat_running",
                new_callable=AsyncMock,
            ),
            patch(
                "app.workflows.persona_heartbeat._execute_heartbeat",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    model_dump=lambda: {"status": "success", "turns": 1, "tool_calls": 0},
                    turns=1,
                    tool_calls=0,
                ),
            ) as mock_execute,
        ):
            result = await _run_persona_heartbeat(
                HeartbeatInput(manual=True, target_project_id="agent-hub"),
                ctx,
            )

        assert result["status"] == "success"
        mock_permission.assert_awaited_once_with("agent-hub")
        mock_execute.assert_awaited_once_with(60, target_project_id="agent-hub")


class TestHeartbeatCompletionRouting:
    """Tests that Claude and Codex use the same heartbeat execution contract."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("model_id", "provider"),
        [
            (CLAUDE_OPUS, "claude"),
            (CODEX_GPT_5_4, "codex"),
        ],
    )
    async def test_do_completion_uses_tools_for_supported_models(self, model_id, provider):
        mock_db = AsyncMock()
        complete_result = SimpleNamespace(content="HEARTBEAT_OK", session_id="sess-1")

        with (
            patch(
                "app.workflows.persona_heartbeat.get_model_review_status",
                new_callable=AsyncMock,
                return_value=(False, "not due"),
            ),
            patch(
                "app.workflows.persona_heartbeat.build_heartbeat_prompt",
                new_callable=AsyncMock,
                return_value="Check the system",
            ),
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.workflows.persona_heartbeat._resolve_persona",
                new_callable=AsyncMock,
                return_value=(model_id, provider, 0.7, "medium", "You are Jenny", None),
            ),
            patch(
                "app.services.persona_service.get_persona",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(limits=None),
            ),
            patch(
                "app.services._persona_crud.get_persona_limit",
                return_value=200,
            ),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                return_value=complete_result,
            ) as mock_complete,
            patch(
                "app.workflows.persona_heartbeat.record_heartbeat",
                new_callable=AsyncMock,
            ),
        ):
            result = await _do_completion(60)

        assert result is complete_result
        mock_complete.assert_awaited_once()
        kwargs = mock_complete.await_args.kwargs
        assert kwargs["model"] == model_id
        assert kwargs["provider"] == provider
        assert kwargs["execute_tools"] is True
        assert kwargs["enable_programmatic_tools"] is True
        assert kwargs["thinking_level"] == "medium"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("model_id", "provider"),
        [
            (CLAUDE_OPUS, "claude"),
            (CODEX_GPT_5_4, "codex"),
        ],
    )
    async def test_do_completion_preserves_shared_contract_for_claude_and_codex(
        self, model_id, provider
    ):
        mock_db = AsyncMock()
        complete_result = SimpleNamespace(content="HEARTBEAT_OK", session_id="sess-1")

        with (
            patch(
                "app.workflows.persona_heartbeat.get_model_review_status",
                new_callable=AsyncMock,
                return_value=(True, "due now"),
            ),
            patch(
                "app.workflows.persona_heartbeat.build_heartbeat_prompt",
                new_callable=AsyncMock,
                return_value="Compare providers",
            ),
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.workflows.persona_heartbeat._resolve_persona",
                new_callable=AsyncMock,
                return_value=(model_id, provider, 0.25, "high", "You are Jenny", {"mode": "auto"}),
            ),
            patch(
                "app.services.persona_service.get_persona",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(limits={"max_turns": 17}),
            ),
            patch(
                "app.services._persona_crud.get_persona_limit",
                return_value=17,
            ),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                return_value=complete_result,
            ) as mock_complete,
            patch(
                "app.workflows.persona_heartbeat.record_heartbeat",
                new_callable=AsyncMock,
            ) as mock_record,
        ):
            result = await _do_completion(45)

        assert result is complete_result
        mock_record.assert_awaited_once_with(did_model_review=True)
        kwargs = mock_complete.await_args.kwargs
        assert kwargs["messages"] == [
            {"role": "system", "content": "You are Jenny"},
            {"role": "user", "content": "Compare providers"},
        ]
        assert kwargs["model"] == model_id
        assert kwargs["provider"] == provider
        assert kwargs["temperature"] == 0.25
        assert kwargs["project_id"] == HEARTBEAT_PROJECT
        assert kwargs["agent_slug"] == "persona"
        assert kwargs["use_memory"] is True
        assert kwargs["memory_group_id"] == HEARTBEAT_MEMORY_GROUP
        assert kwargs["memory_config"] == {"mode": "auto"}
        assert kwargs["enable_caching"] is False
        assert kwargs["skip_cache"] is True
        assert kwargs["max_turns"] == 17
        assert kwargs["execute_tools"] is True
        assert kwargs["enable_programmatic_tools"] is True
        assert kwargs["task_type"] == "heartbeat"
        assert kwargs["thinking_level"] == "high"

    @pytest.mark.asyncio
    async def test_do_completion_uses_target_project_for_execution_scope(self):
        mock_db = AsyncMock()
        complete_result = SimpleNamespace(content="HEARTBEAT_OK", session_id="sess-1")

        with (
            patch(
                "app.workflows.persona_heartbeat.get_model_review_status",
                new_callable=AsyncMock,
                return_value=(False, "not due"),
            ),
            patch(
                "app.workflows.persona_heartbeat.build_heartbeat_prompt",
                new_callable=AsyncMock,
                return_value="Focus on agent-hub",
            ) as mock_prompt,
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.workflows.persona_heartbeat._resolve_persona",
                new_callable=AsyncMock,
                return_value=("claude-sonnet-4-6", "claude", 0.2, "medium", "You are Jenny", {"mode": "auto"}),
            ) as mock_resolve_persona,
            patch(
                "app.services.persona_service.get_persona",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(limits=None),
            ),
            patch(
                "app.services._persona_crud.get_persona_limit",
                return_value=200,
            ),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                return_value=complete_result,
            ) as mock_complete,
            patch(
                "app.workflows.persona_heartbeat.record_heartbeat",
                new_callable=AsyncMock,
            ),
        ):
            result = await _do_completion(60, target_project_id="agent-hub")

        assert result is complete_result
        mock_prompt.assert_awaited_once_with(
            False,
            "not due",
            target_project_id="agent-hub",
            provider="claude",
        )
        mock_resolve_persona.assert_awaited_once_with(mock_db, project_id="agent-hub")
        kwargs = mock_complete.await_args.kwargs
        assert kwargs["project_id"] == "agent-hub"
        assert kwargs["memory_group_id"] == HEARTBEAT_MEMORY_GROUP
        assert kwargs["working_dir"] == KNOWN_ROOTS["agent-hub"]
