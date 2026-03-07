"""Tests for persona heartbeat runtime compatibility and execution behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.models import CLAUDE_OPUS, CODEX_GPT_5_4
from app.workflows.persona_heartbeat import (
    HeartbeatInput,
    _do_completion,
    _run_persona_heartbeat,
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
            "codex/gpt-5.1-codex-mini",
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
        assert runtime.warnings == [
            "Heartbeat requires tool execution, but codex/gpt-5.1-codex-mini does not support tools."
        ]


class TestPersonaHeartbeatTask:
    """Tests for heartbeat task compatibility guardrails."""

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
                "app.workflows.persona_heartbeat.check_project_permission",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workflows.persona_heartbeat.get_heartbeat_runtime_info",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(
                    heartbeat_supported=False,
                    warnings=["Heartbeat requires tool execution, but codex/gpt-5.1-codex-mini does not support tools."],
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
        assert result["error"] == "Heartbeat requires tool execution, but codex/gpt-5.1-codex-mini does not support tools."
        mock_set_running.assert_not_awaited()
        mock_execute.assert_not_awaited()

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
        mock_execute.assert_awaited_once_with(60)


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
