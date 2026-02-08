"""Tests for async completion API endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import APITestClient


def _mock_agent() -> MagicMock:
    mock_agent = MagicMock()
    mock_agent.model = "claude-sonnet-4-5"
    mock_agent.provider = "claude"
    mock_agent.agent.slug = "coder"
    mock_agent.agent.fallback_models = []
    mock_agent.agent.memory_config = None
    mock_agent.agent.tool_permissions = None
    return mock_agent


def _mock_context_patches() -> tuple[MagicMock, MagicMock, MagicMock]:
    mock_memory_ctx = MagicMock(mandates=[], guardrails=[], reference=[], get_loaded_uuids=lambda: [])
    mock_ctx_usage = MagicMock()
    mock_ctx_usage.used_tokens = 100
    mock_ctx_usage.limit_tokens = 200000
    mock_ctx_usage.percent_used = 0.0005
    mock_ctx_usage.remaining_tokens = 199900
    mock_ctx_usage.warning = None
    mock_cache_inst = MagicMock()
    mock_cache_inst.get = AsyncMock(return_value=None)
    return mock_memory_ctx, mock_ctx_usage, mock_cache_inst


class TestAsyncDispatch:
    def test_async_execution_returns_202(
        self, api_client: APITestClient, mock_db_session: MagicMock
    ) -> None:
        mock_memory_ctx, mock_ctx_usage, mock_cache_inst = _mock_context_patches()

        with (
            patch("app.api.complete.endpoints.resolve_agent") as mock_resolve,
            patch("app.api.complete.endpoints.inject_agent_mandates", return_value=None),
            patch(
                "app.api.complete.endpoints.inject_progressive_context",
                return_value=([{"role": "user", "content": "hello"}], mock_memory_ctx),
            ),
            patch(
                "app.api.complete.endpoints.check_context_before_request",
                return_value=(True, mock_ctx_usage),
            ),
            patch("app.api.complete.endpoints.get_response_cache", return_value=mock_cache_inst),
            patch("app.tasks.completion_task.run_agentic_completion") as mock_task,
            patch("app.api.complete.endpoints.get_or_create_session") as mock_session,
            patch("app.api.complete.endpoints.store_memory_inject_event"),
            patch("app.api.complete.endpoints.publish_session_start"),
        ):
            mock_resolve.return_value = _mock_agent()

            mock_db_session_obj = MagicMock()
            mock_db_session_obj.id = "sess-test-123"
            mock_db_session_obj.status = "active"
            mock_session.return_value = (mock_db_session_obj, [], True)

            mock_apply = MagicMock()
            mock_task.apply_async = mock_apply

            response = api_client.post(
                "/api/complete",
                json={
                    "agent_slug": "coder",
                    "project_id": "test-project",
                    "messages": [{"role": "user", "content": "Build a feature"}],
                    "max_turns": 5,
                    "execute_tools": True,
                    "async_execution": True,
                },
            )

            assert response.status_code == 202
            data = response.json()
            assert "task_id" in data
            assert data["status"] == "pending"
            assert "poll_url" in data
            assert "events_channel" in data
            mock_apply.assert_called_once()

    def test_async_with_stream_returns_400(
        self, api_client: APITestClient, mock_db_session: MagicMock
    ) -> None:
        with (
            patch("app.api.complete.endpoints.resolve_agent", return_value=_mock_agent()),
            patch("app.api.complete.endpoints.inject_agent_mandates", return_value=None),
        ):
            response = api_client.post(
                "/api/complete",
                json={
                    "agent_slug": "coder",
                    "project_id": "test-project",
                    "messages": [{"role": "user", "content": "Build a feature"}],
                    "max_turns": 5,
                    "execute_tools": True,
                    "async_execution": True,
                    "stream": True,
                },
            )

            assert response.status_code == 400


class TestAsyncTaskStatus:
    @pytest.mark.asyncio
    async def test_get_status_completed(self) -> None:
        from app.api.complete.async_endpoints import get_task_status

        stored: dict[str, Any] = {
            "task_id": "task-123",
            "content": "Done",
            "model": "claude-sonnet-4-5",
            "provider": "claude",
            "input_tokens": 100,
            "output_tokens": 50,
            "finish_reason": "end_turn",
            "session_id": "sess-456",
            "memory_uuids": [],
            "cited_uuids": [],
            "turns": 3,
            "tool_calls_count": 2,
            "status": "success",
            "progress_log": [],
        }

        with (
            patch("app.api.complete.async_endpoints.get_task_result", new_callable=AsyncMock, return_value=stored),
            patch("app.api.complete.async_endpoints.AsyncResult") as mock_ar,
        ):
            mock_ar.return_value.state = "SUCCESS"
            result = await get_task_status("task-123")

        assert result.status == "completed"
        assert result.result is not None
        assert result.result.content == "Done"

    @pytest.mark.asyncio
    async def test_get_status_failed(self) -> None:
        from app.api.complete.async_endpoints import get_task_status

        stored: dict[str, Any] = {
            "task_id": "task-err",
            "session_id": "sess-1",
            "status": "failed",
            "error": "Timeout exceeded",
        }

        with (
            patch("app.api.complete.async_endpoints.get_task_result", new_callable=AsyncMock, return_value=stored),
            patch("app.api.complete.async_endpoints.AsyncResult") as mock_ar,
        ):
            mock_ar.return_value.state = "FAILURE"
            result = await get_task_status("task-err")

        assert result.status == "failed"
        assert result.error == "Timeout exceeded"

    @pytest.mark.asyncio
    async def test_get_status_unknown(self) -> None:
        from app.api.complete.async_endpoints import get_task_status

        with (
            patch("app.api.complete.async_endpoints.get_task_result", new_callable=AsyncMock, return_value=None),
            patch("app.api.complete.async_endpoints.AsyncResult") as mock_ar,
        ):
            mock_ar.return_value.state = "PENDING"
            result = await get_task_status("nonexistent")

        assert result.status == "unknown"

    @pytest.mark.asyncio
    async def test_get_status_started(self) -> None:
        from app.api.complete.async_endpoints import get_task_status

        with (
            patch("app.api.complete.async_endpoints.get_task_result", new_callable=AsyncMock, return_value=None),
            patch("app.api.complete.async_endpoints.AsyncResult") as mock_ar,
        ):
            mock_ar.return_value.state = "STARTED"
            result = await get_task_status("task-running")

        assert result.status == "started"


class TestCancelTask:
    @pytest.mark.asyncio
    async def test_cancel_running_task(self) -> None:
        from app.api.complete.async_endpoints import cancel_task

        with patch("app.api.complete.async_endpoints.AsyncResult") as mock_ar:
            mock_ar.return_value.state = "STARTED"
            result = await cancel_task("task-running")

        assert result["status"] == "cancelled"
        mock_ar.return_value.revoke.assert_called_once_with(terminate=True, signal="SIGTERM")

    @pytest.mark.asyncio
    async def test_cancel_completed_task_returns_409(self) -> None:
        from fastapi import HTTPException

        from app.api.complete.async_endpoints import cancel_task

        with patch("app.api.complete.async_endpoints.AsyncResult") as mock_ar:
            mock_ar.return_value.state = "SUCCESS"
            with pytest.raises(HTTPException) as exc_info:
                await cancel_task("task-done")
            assert exc_info.value.status_code == 409


class TestNonAgenticAsyncFallsThrough:
    def test_non_agentic_async_executes_sync(
        self, api_client: APITestClient, mock_db_session: MagicMock
    ) -> None:
        """async_execution=True with max_turns=1 and execute_tools=False executes synchronously."""
        mock_memory_ctx, mock_ctx_usage, mock_cache_inst = _mock_context_patches()

        from app.api.complete.core import CompletionInternalResult

        mock_internal = CompletionInternalResult(
            content="sync response",
            model="claude-sonnet-4-5",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
            session_id="sess-test-456",
            memory_uuids=[],
            cited_uuids=[],
        )

        with (
            patch("app.api.complete.endpoints.resolve_agent") as mock_resolve,
            patch("app.api.complete.endpoints.inject_agent_mandates", return_value=None),
            patch(
                "app.api.complete.endpoints.inject_progressive_context",
                return_value=([{"role": "user", "content": "hello"}], mock_memory_ctx),
            ),
            patch(
                "app.api.complete.endpoints.check_context_before_request",
                return_value=(True, mock_ctx_usage),
            ),
            patch("app.api.complete.endpoints.get_response_cache", return_value=mock_cache_inst),
            patch("app.api.complete.endpoints.complete_internal", new_callable=AsyncMock, return_value=mock_internal),
            patch("app.api.complete.endpoints.get_or_create_session") as mock_session,
            patch("app.api.complete.endpoints.store_memory_inject_event"),
            patch("app.api.complete.endpoints.publish_session_start"),
        ):
            mock_resolve.return_value = _mock_agent()

            mock_db_session_obj = MagicMock()
            mock_db_session_obj.id = "sess-test-456"
            mock_db_session_obj.status = "active"
            mock_session.return_value = (mock_db_session_obj, [], True)

            response = api_client.post(
                "/api/complete",
                json={
                    "agent_slug": "coder",
                    "project_id": "test-project",
                    "messages": [{"role": "user", "content": "hello"}],
                    "max_turns": 1,
                    "execute_tools": False,
                    "async_execution": True,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["content"] == "sync response"


class TestBackwardsCompat:
    def test_sync_execution_still_works(
        self, api_client: APITestClient, mock_db_session: MagicMock
    ) -> None:
        """Default async_execution=False still returns sync response for agentic requests."""
        mock_memory_ctx, mock_ctx_usage, mock_cache_inst = _mock_context_patches()

        from app.api.complete.core import CompletionInternalResult

        mock_internal = CompletionInternalResult(
            content="agentic sync response",
            model="claude-sonnet-4-5",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
            session_id="sess-test-789",
            memory_uuids=[],
            cited_uuids=[],
            status="success",
            turns=3,
            tool_calls_count=2,
        )

        with (
            patch("app.api.complete.endpoints.resolve_agent") as mock_resolve,
            patch("app.api.complete.endpoints.inject_agent_mandates", return_value=None),
            patch(
                "app.api.complete.endpoints.inject_progressive_context",
                return_value=([{"role": "user", "content": "hello"}], mock_memory_ctx),
            ),
            patch(
                "app.api.complete.endpoints.check_context_before_request",
                return_value=(True, mock_ctx_usage),
            ),
            patch("app.api.complete.endpoints.get_response_cache", return_value=mock_cache_inst),
            patch("app.api.complete.endpoints.complete_internal", new_callable=AsyncMock, return_value=mock_internal),
            patch("app.api.complete.endpoints.get_or_create_session") as mock_session,
            patch("app.api.complete.endpoints.store_memory_inject_event"),
            patch("app.api.complete.endpoints.publish_session_start"),
            patch("app.tasks.completion_task.run_agentic_completion") as mock_task,
        ):
            mock_resolve.return_value = _mock_agent()

            mock_db_session_obj = MagicMock()
            mock_db_session_obj.id = "sess-test-789"
            mock_db_session_obj.status = "active"
            mock_session.return_value = (mock_db_session_obj, [], True)

            response = api_client.post(
                "/api/complete",
                json={
                    "agent_slug": "coder",
                    "project_id": "test-project",
                    "messages": [{"role": "user", "content": "Build something"}],
                    "max_turns": 5,
                    "execute_tools": True,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["content"] == "agentic sync response"
            mock_task.apply_async.assert_not_called()


class TestGetTaskStatusViaAPI:
    def test_get_status_endpoint_completed(
        self, api_client: APITestClient
    ) -> None:
        """GET /api/complete/tasks/{task_id} returns completed status."""
        stored: dict[str, Any] = {
            "task_id": "task-api-1",
            "content": "Result from worker",
            "model": "claude-sonnet-4-5",
            "provider": "claude",
            "input_tokens": 100,
            "output_tokens": 50,
            "finish_reason": "end_turn",
            "session_id": "sess-api-1",
            "memory_uuids": [],
            "cited_uuids": [],
            "turns": 2,
            "tool_calls_count": 1,
            "status": "success",
            "progress_log": [],
        }

        with (
            patch("app.api.complete.async_endpoints.get_task_result", new_callable=AsyncMock, return_value=stored),
            patch("app.api.complete.async_endpoints.AsyncResult") as mock_ar,
        ):
            mock_ar.return_value.state = "SUCCESS"
            response = api_client.get("/api/complete/tasks/task-api-1")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"]["content"] == "Result from worker"

    def test_cancel_endpoint(self, api_client: APITestClient) -> None:
        """DELETE /api/complete/tasks/{task_id}/cancel cancels running task."""
        with patch("app.api.complete.async_endpoints.AsyncResult") as mock_ar:
            mock_ar.return_value.state = "STARTED"
            response = api_client.delete("/api/complete/tasks/task-cancel-1/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"
