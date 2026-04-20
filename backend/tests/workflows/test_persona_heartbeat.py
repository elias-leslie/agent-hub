"""Tests for persona heartbeat runtime compatibility and execution behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.models import CLAUDE_OPUS, CODEX_GPT_5_1_MINI, CODEX_GPT_5_4
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
            "You are Persona",
            None,
        )

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.workflows._heartbeat_steps._resolve_persona",
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
            "You are Persona",
            None,
        )

        with (
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.workflows._heartbeat_steps._resolve_persona",
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
                "app.workflows._heartbeat_steps._resolve_persona",
                new_callable=AsyncMock,
                return_value=(model_id, provider, 0.7, "medium", "You are Persona", None),
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
                "app.workflows._heartbeat_steps.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows._heartbeat_steps.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="paused",
            ),
            patch(
                "app.workflows._heartbeat_steps.check_redis_elapsed",
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
                "app.workflows._heartbeat_steps.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows._heartbeat_steps.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.workflows._heartbeat_steps.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_runtime_info",
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
                "app.workflows.persona_heartbeat.record_heartbeat_skip",
                new_callable=AsyncMock,
            ) as mock_skip,
        ):
            result = await _run_persona_heartbeat(HeartbeatInput(manual=True), ctx)

        assert result["status"] == "skipped"
        assert result["error"] == f"runtime_incompatible: {_build_runtime_warning(CODEX_GPT_5_1_MINI)}"
        mock_set_running.assert_not_awaited()
        mock_skip.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_manual_heartbeat_uses_model_name_from_runtime_when_warning_missing(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows._heartbeat_steps.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.workflows._heartbeat_steps.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_runtime_info",
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
                "app.workflows.persona_heartbeat.record_heartbeat_skip",
                new_callable=AsyncMock,
            ) as mock_skip,
            patch(
                "app.workflows.persona_heartbeat._do_completion",
                new_callable=AsyncMock,
            ) as mock_execute,
        ):
            result = await _run_persona_heartbeat(HeartbeatInput(manual=True), ctx)

        assert result["status"] == "skipped"
        assert result["error"] == f"runtime_incompatible: {_build_runtime_warning('claude/unknown-no-tools')}"
        mock_set_running.assert_not_awaited()
        mock_execute.assert_not_awaited()
        mock_skip.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_manual_heartbeat_skips_when_persona_is_paused(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows._heartbeat_steps.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="paused",
            ),
            patch(
                "app.workflows._heartbeat_steps.check_project_permission",
                new_callable=AsyncMock,
            ) as mock_permission,
            patch(
                "app.workflows.persona_heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
            ) as mock_set_running,
            patch(
                "app.workflows.persona_heartbeat.record_heartbeat_skip",
                new_callable=AsyncMock,
            ) as mock_skip,
        ):
            result = await _run_persona_heartbeat(HeartbeatInput(manual=True), ctx)

        assert result["status"] == "skipped"
        mock_permission.assert_not_awaited()
        mock_set_running.assert_not_awaited()
        mock_skip.assert_awaited_once_with("paused")

    @pytest.mark.asyncio
    async def test_manual_heartbeat_runs_when_runtime_is_supported(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows._heartbeat_steps.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.workflows._heartbeat_steps.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    heartbeat_supported=True,
                    warnings=[],
                ),
            ),
            patch(
                "app.workflows.persona_heartbeat.record_heartbeat_attempt",
                new_callable=AsyncMock,
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
                "app.workflows.persona_heartbeat._do_completion",
                new_callable=AsyncMock,
                return_value=(SimpleNamespace(content="HEARTBEAT_OK"), False),
            ) as mock_do_completion,
            patch(
                "app.workflows.persona_heartbeat.postprocess_heartbeat",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    status="success",
                    turns=3,
                    tool_calls=2,
                    model_dump=lambda: {"status": "success", "turns": 3, "tool_calls": 2},
                ),
            ),
            patch(
                "app.workflows._heartbeat_steps.record_heartbeat_success",
                new_callable=AsyncMock,
            ) as mock_success,
        ):
            result = await _run_persona_heartbeat(HeartbeatInput(manual=True), ctx)

        assert result["status"] == "success"
        mock_do_completion.assert_awaited_once()
        mock_success.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_manual_heartbeat_passes_target_project_to_execution(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows._heartbeat_steps.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.workflows._heartbeat_steps.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_permission,
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    heartbeat_supported=True,
                    warnings=[],
                ),
            ),
            patch(
                "app.workflows.persona_heartbeat.record_heartbeat_attempt",
                new_callable=AsyncMock,
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
                "app.workflows.persona_heartbeat._do_completion",
                new_callable=AsyncMock,
                return_value=(SimpleNamespace(content="HEARTBEAT_OK"), False),
            ) as mock_do_completion,
            patch(
                "app.workflows.persona_heartbeat.postprocess_heartbeat",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    status="success",
                    turns=1,
                    tool_calls=0,
                    model_dump=lambda: {"status": "success", "turns": 1, "tool_calls": 0},
                ),
            ),
            patch(
                "app.workflows._heartbeat_steps.record_heartbeat_success",
                new_callable=AsyncMock,
            ),
        ):
            result = await _run_persona_heartbeat(
                HeartbeatInput(manual=True, target_project_id="agent-hub"),
                ctx,
            )

        assert result["status"] == "success"
        mock_permission.assert_awaited_once_with("agent-hub")
        mock_do_completion.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_manual_heartbeat_reuses_provided_session_id(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows._heartbeat_steps.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.workflows._heartbeat_steps.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    heartbeat_supported=True,
                    warnings=[],
                ),
            ),
            patch(
                "app.workflows.persona_heartbeat.record_heartbeat_attempt",
                new_callable=AsyncMock,
            ) as mock_attempt,
            patch(
                "app.workflows.persona_heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
                return_value="claim-provided",
            ) as mock_set_running,
            patch(
                "app.workflows.persona_heartbeat.clear_heartbeat_running",
                new_callable=AsyncMock,
            ) as mock_clear_running,
            patch(
                "app.workflows.persona_heartbeat._do_completion",
                new_callable=AsyncMock,
                return_value=(SimpleNamespace(content="HEARTBEAT_OK"), False),
            ) as mock_do_completion,
            patch(
                "app.workflows.persona_heartbeat.postprocess_heartbeat",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    status="success",
                    turns=1,
                    tool_calls=0,
                    model_dump=lambda: {"status": "success", "turns": 1, "tool_calls": 0},
                ),
            ),
            patch(
                "app.workflows._heartbeat_steps.record_heartbeat_success",
                new_callable=AsyncMock,
            ),
        ):
            result = await _run_persona_heartbeat(
                HeartbeatInput(manual=True, heartbeat_session_id="hb-session-provided"),
                ctx,
            )

        assert result["status"] == "success"
        mock_attempt.assert_awaited_once_with(session_id="hb-session-provided")
        mock_set_running.assert_awaited_once_with(
            session_id="hb-session-provided",
            trigger="manual",
            project_id=HEARTBEAT_PROJECT,
            only_if_missing=True,
        )
        mock_do_completion.assert_awaited_once()
        assert mock_do_completion.await_args.kwargs["heartbeat_session_id"] == "hb-session-provided"
        mock_clear_running.assert_awaited_once_with(
            claim_token="claim-provided",
            session_id="hb-session-provided",
        )

    @pytest.mark.asyncio
    async def test_manual_heartbeat_skips_reclaim_when_api_already_reserved_run(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows._heartbeat_steps.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.workflows._heartbeat_steps.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    heartbeat_supported=True,
                    warnings=[],
                ),
            ),
            patch(
                "app.workflows.persona_heartbeat.record_heartbeat_attempt",
                new_callable=AsyncMock,
            ) as mock_attempt,
            patch(
                "app.workflows.persona_heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
            ) as mock_set_running,
            patch(
                "app.workflows.persona_heartbeat.clear_heartbeat_running",
                new_callable=AsyncMock,
            ) as mock_clear_running,
            patch(
                "app.workflows.persona_heartbeat._do_completion",
                new_callable=AsyncMock,
                return_value=(SimpleNamespace(content="HEARTBEAT_OK"), False),
            ) as mock_do_completion,
            patch(
                "app.workflows.persona_heartbeat.postprocess_heartbeat",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    status="success",
                    turns=1,
                    tool_calls=0,
                    model_dump=lambda: {"status": "success", "turns": 1, "tool_calls": 0},
                ),
            ),
            patch(
                "app.workflows._heartbeat_steps.record_heartbeat_success",
                new_callable=AsyncMock,
            ),
        ):
            result = await _run_persona_heartbeat(
                HeartbeatInput(
                    manual=True,
                    heartbeat_session_id="hb-session-reserved",
                    running_claimed=True,
                    running_claim_token="claim-preclaimed",
                ),
                ctx,
            )

        assert result["status"] == "success"
        mock_attempt.assert_not_awaited()
        mock_set_running.assert_not_awaited()
        assert mock_do_completion.await_args.kwargs["heartbeat_session_id"] == "hb-session-reserved"
        mock_clear_running.assert_awaited_once_with(
            claim_token="claim-preclaimed",
            session_id="hb-session-reserved",
        )

    @pytest.mark.asyncio
    async def test_manual_heartbeat_skips_when_lock_claim_fails(self):
        ctx = SimpleNamespace(log=MagicMock())

        with (
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows._heartbeat_steps.get_persona_execution_state",
                new_callable=AsyncMock,
                return_value="active",
            ),
            patch(
                "app.workflows._heartbeat_steps.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows._heartbeat_steps.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    heartbeat_supported=True,
                    warnings=[],
                ),
            ),
            patch(
                "app.workflows.persona_heartbeat.record_heartbeat_attempt",
                new_callable=AsyncMock,
            ) as mock_attempt,
            patch(
                "app.workflows.persona_heartbeat.set_heartbeat_running",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_set_running,
            patch(
                "app.workflows.persona_heartbeat.record_heartbeat_skip",
                new_callable=AsyncMock,
            ) as mock_skip,
            patch(
                "app.workflows.persona_heartbeat.clear_heartbeat_running",
                new_callable=AsyncMock,
            ) as mock_clear_running,
            patch(
                "app.workflows.persona_heartbeat._do_completion",
                new_callable=AsyncMock,
            ) as mock_do_completion,
        ):
            result = await _run_persona_heartbeat(
                HeartbeatInput(manual=True, heartbeat_session_id="hb-session-raced"),
                ctx,
            )

        assert result["status"] == "skipped"
        assert result["error"] == "already_running"
        mock_attempt.assert_awaited_once_with(session_id="hb-session-raced")
        mock_set_running.assert_awaited_once_with(
            session_id="hb-session-raced",
            trigger="manual",
            project_id=HEARTBEAT_PROJECT,
            only_if_missing=True,
        )
        mock_skip.assert_awaited_once_with("already_running", session_id="hb-session-raced")
        mock_do_completion.assert_not_awaited()
        mock_clear_running.assert_not_awaited()


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
                "app.workflows._heartbeat_steps.get_model_review_status",
                new_callable=AsyncMock,
                return_value=(False, "not due"),
            ),
            patch(
                "app.workflows._heartbeat_steps.build_heartbeat_prompt",
                new_callable=AsyncMock,
                return_value="Check the system",
            ),
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.workflows._heartbeat_steps._resolve_persona",
                new_callable=AsyncMock,
                return_value=(model_id, provider, 0.7, "medium", "You are Persona", None),
            ),
            patch(
                "app.services.persona_service.get_persona",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(limits=None),
            ),
            patch(
                "app.services._persona_crud.get_persona_limit",
                return_value=500,
            ),
            patch(
                "app.workflows._heartbeat_steps.resolve_project_root",
                return_value=Path("/tmp/agent-hub"),
            ),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                return_value=complete_result,
            ) as mock_complete,
        ):
            result, model_review_due = await _do_completion(60, heartbeat_session_id="hb-session-1")

        assert result is complete_result
        assert model_review_due is False
        mock_complete.assert_awaited_once()
        kwargs = mock_complete.await_args.kwargs
        assert kwargs["model"] == model_id
        assert kwargs["provider"] == provider
        assert kwargs["session_id"] == "hb-session-1"
        assert kwargs["request_source"] == "heartbeat"
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
                "app.workflows._heartbeat_steps.get_model_review_status",
                new_callable=AsyncMock,
                return_value=(True, "due now"),
            ),
            patch(
                "app.workflows._heartbeat_steps.build_heartbeat_prompt",
                new_callable=AsyncMock,
                return_value="Compare providers",
            ),
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.workflows._heartbeat_steps._resolve_persona",
                new_callable=AsyncMock,
                return_value=(model_id, provider, 0.25, "high", "You are Persona", {"mode": "auto"}),
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
        ):
            result, model_review_due = await _do_completion(45, heartbeat_session_id="hb-session-2")

        assert result is complete_result
        assert model_review_due is True
        kwargs = mock_complete.await_args.kwargs
        assert kwargs["messages"] == [
            {"role": "system", "content": "You are Persona"},
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
        assert kwargs["session_id"] == "hb-session-2"
        assert kwargs["request_source"] == "heartbeat"

    @pytest.mark.asyncio
    async def test_do_completion_uses_target_project_for_execution_scope(self):
        mock_db = AsyncMock()
        complete_result = SimpleNamespace(content="HEARTBEAT_OK", session_id="sess-1")

        with (
            patch(
                "app.workflows._heartbeat_steps.get_model_review_status",
                new_callable=AsyncMock,
                return_value=(False, "not due"),
            ),
            patch(
                "app.workflows._heartbeat_steps.build_heartbeat_prompt",
                new_callable=AsyncMock,
                return_value="Focus on agent-hub",
            ) as mock_prompt,
            patch("app.db.async_session", _mock_async_session(mock_db)),
            patch(
                "app.workflows._heartbeat_steps._resolve_persona",
                new_callable=AsyncMock,
                return_value=("claude-sonnet-4-6", "claude", 0.2, "medium", "You are Persona", {"mode": "auto"}),
            ) as mock_resolve_persona,
            patch(
                "app.services.persona_service.get_persona",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(limits=None),
            ),
            patch(
                "app.services._persona_crud.get_persona_limit",
                return_value=500,
            ),
            patch(
                "app.workflows._heartbeat_steps.resolve_project_root",
                return_value=Path("/tmp/agent-hub"),
            ),
            patch(
                "app.api.complete.core.complete_internal",
                new_callable=AsyncMock,
                return_value=complete_result,
            ) as mock_complete,
        ):
            result, model_review_due = await _do_completion(
                60,
                heartbeat_session_id="hb-session-3",
                target_project_id="agent-hub",
            )

        assert result is complete_result
        assert model_review_due is False
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
        assert kwargs["working_dir"] == "/tmp/agent-hub"
        assert kwargs["session_id"] == "hb-session-3"


def test_heartbeat_result_accepts_budget_fields() -> None:
    from app.workflows.persona_heartbeat import HeartbeatResult

    result = HeartbeatResult(status="ok", error=None)

    assert result.status == "ok"
