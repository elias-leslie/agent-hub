"""Tests for async completion API endpoints."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse

from app.constants.models import CLAUDE_SONNET
from tests.conftest import APITestClient

# Patch target: orchestrator imports at top-level from sub-modules
_ORCH = "app.api.complete.complete_orchestrator"


def _mock_agent() -> MagicMock:
    mock_agent = MagicMock()
    mock_agent.model = CLAUDE_SONNET
    mock_agent.provider = "claude"
    mock_agent.agent.slug = "coder"
    mock_agent.agent.fallback_models = []
    mock_agent.agent.memory_config = None
    mock_agent.agent.hourly_request_limit = None
    mock_agent.agent.daily_token_budget = None
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


def _mock_budget_allowed() -> MagicMock:
    """Return a mock BudgetCheckResult that allows the request."""
    result = MagicMock()
    result.allowed = True
    result.reason = None
    result.daily_usage_usd = 0.0
    result.monthly_usage_usd = 0.0
    result.daily_limit_usd = None
    result.monthly_limit_usd = None
    result.alert_level = None
    return result


def _mock_redis_client() -> MagicMock:
    mock_client = MagicMock()

    async def mock_setex(*args: Any, **kwargs: Any) -> None:
        pass

    async def mock_get(key: str) -> bytes | None:
        return b"run-id-123"

    async def mock_close() -> None:
        pass

    mock_client.setex = mock_setex
    mock_client.get = mock_get
    mock_client.close = mock_close
    return mock_client


class TestAsyncDispatch:
    def test_async_execution_returns_202(
        self, api_client: APITestClient, mock_db_session: MagicMock
    ) -> None:
        _mock_memory_ctx, _mock_ctx_usage, _mock_cache_inst = _mock_context_patches()
        agent = _mock_agent()

        mock_db_session_obj = MagicMock()
        mock_db_session_obj.id = "sess-test-123"
        mock_db_session_obj.status = "active"

        mock_async_response = JSONResponse(
            status_code=202,
            content={
                "task_id": "task-123",
                "session_id": "sess-test-123",
                "status": "pending",
                "poll_url": "/api/complete/tasks/task-123",
                "events_channel": "hatchet:stream:run-123",
                "trace_id": None,
            },
        )

        with (
            patch(f"{_ORCH}.validate_agent_slug", new_callable=AsyncMock),
            patch(f"{_ORCH}.validate_project_access"),
            patch(
                f"{_ORCH}.resolve_agent_and_model",
                new_callable=AsyncMock,
                return_value=(CLAUDE_SONNET, "claude", agent, None, "coder"),
            ),
            patch(
                f"{_ORCH}.apply_mention_override",
                return_value=(CLAUDE_SONNET, "claude"),
            ),
            patch(
                f"{_ORCH}.build_session_and_messages",
                new_callable=AsyncMock,
                return_value=(
                    True,  # is_agentic
                    "sess-test-123",  # session_id
                    mock_db_session_obj,  # session
                    True,  # is_new_session
                    [{"role": "user", "content": "Build a feature"}],  # all_messages
                    [{"role": "user", "content": "Build a feature"}],  # messages_dict
                    0,  # memory_facts
                    [],  # loaded_uuids
                    None,  # context_usage_info
                    None,  # cached
                ),
            ),
            patch(
                "app.services.project_budget.check_project_budget",
                new_callable=AsyncMock,
                return_value=_mock_budget_allowed(),
            ),
            patch(
                f"{_ORCH}.dispatch_async_completion",
                new_callable=AsyncMock,
                return_value=mock_async_response,
            ),
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
                },
            )

            assert response.status_code == 202
            data = response.json()
            assert "task_id" in data
            assert data["status"] == "pending"
            assert "poll_url" in data
            assert "events_channel" in data

    def test_async_with_stream_returns_400(
        self, api_client: APITestClient, mock_db_session: MagicMock
    ) -> None:
        """async_execution + stream is validated early and returns 400."""
        # No mocks needed — validation fires before any internal logic
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

    def test_agentic_cancelled_error_returns_500(
        self, api_client: APITestClient, mock_db_session: MagicMock
    ) -> None:
        agent = _mock_agent()
        mock_db_session_obj = MagicMock()
        mock_db_session_obj.id = "sess-test-123"
        mock_db_session_obj.status = "active"

        with (
            patch(f"{_ORCH}.validate_agent_slug", new_callable=AsyncMock),
            patch(f"{_ORCH}.validate_project_access"),
            patch(
                f"{_ORCH}.resolve_agent_and_model",
                new_callable=AsyncMock,
                return_value=(CLAUDE_SONNET, "claude", agent, None, "coder"),
            ),
            patch(
                f"{_ORCH}.apply_mention_override",
                return_value=(CLAUDE_SONNET, "claude"),
            ),
            patch(
                f"{_ORCH}.build_session_and_messages",
                new_callable=AsyncMock,
                return_value=(
                    True,
                    "sess-test-123",
                    mock_db_session_obj,
                    True,
                    [{"role": "user", "content": "Build a feature"}],
                    [{"role": "user", "content": "Build a feature"}],
                    0,
                    [],
                    None,
                    None,
                ),
            ),
            patch(
                "app.services.project_budget.check_project_budget",
                new_callable=AsyncMock,
                return_value=_mock_budget_allowed(),
            ),
            patch(
                "app.api.complete.orchestration_helpers.execute_completion",
                new_callable=AsyncMock,
                side_effect=asyncio.CancelledError("sdk cancelled"),
            ),
        ):
            response = api_client.post(
                "/api/complete",
                json={
                    "agent_slug": "coder",
                    "project_id": "test-project",
                    "messages": [{"role": "user", "content": "Build a feature"}],
                    "max_turns": 5,
                    "execute_tools": True,
                },
            )

        assert response.status_code == 500
        payload = response.json()
        assert payload["error"] == "http_error"
        assert payload["message"] == "Completion cancelled unexpectedly."


class TestAsyncTaskStatus:
    @pytest.mark.asyncio
    async def test_get_status_completed(self) -> None:
        from app.api.complete.async_endpoints import get_task_status

        stored: dict[str, Any] = {
            "task_id": "task-123",
            "content": "Done",
            "model": CLAUDE_SONNET,
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

        with patch("app.api.complete.async_endpoints.get_task_result", new_callable=AsyncMock, return_value=stored):
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

        with patch("app.api.complete.async_endpoints.get_task_result", new_callable=AsyncMock, return_value=stored):
            result = await get_task_status("task-err")

        assert result.status == "failed"
        assert result.error == "Timeout exceeded"

    @pytest.mark.asyncio
    async def test_get_status_started(self) -> None:
        from app.api.complete.async_endpoints import get_task_status

        mock_redis = _mock_redis_client()

        with (
            patch("app.api.complete.async_endpoints.get_task_result", new_callable=AsyncMock, return_value=None),
            patch("app.api.complete.async_endpoints.AsyncRedis") as mock_redis_cls,
        ):
            mock_redis_cls.from_url.return_value = mock_redis
            result = await get_task_status("task-running")

        assert result.status == "started"

    @pytest.mark.asyncio
    async def test_get_status_unknown(self) -> None:
        from app.api.complete.async_endpoints import get_task_status

        mock_redis = MagicMock()

        async def mock_get(key: str) -> None:
            return None

        async def mock_close() -> None:
            pass

        mock_redis.get = mock_get
        mock_redis.close = mock_close

        with (
            patch("app.api.complete.async_endpoints.get_task_result", new_callable=AsyncMock, return_value=None),
            patch("app.api.complete.async_endpoints.AsyncRedis") as mock_redis_cls,
        ):
            mock_redis_cls.from_url.return_value = mock_redis
            result = await get_task_status("nonexistent")

        assert result.status == "unknown"


class TestCancelTask:
    @pytest.mark.asyncio
    async def test_cancel_running_task(self) -> None:
        from app.api.complete.async_endpoints import cancel_task

        mock_redis = _mock_redis_client()
        mock_hatchet = MagicMock()
        mock_hatchet.runs.aio_cancel = AsyncMock()

        with (
            patch("app.api.complete.async_endpoints.AsyncRedis") as mock_redis_cls,
            patch("app.hatchet_app.hatchet", mock_hatchet),
        ):
            mock_redis_cls.from_url.return_value = mock_redis
            result = await cancel_task("task-running")

        assert result["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_completed_task_returns_409(self) -> None:
        from fastapi import HTTPException

        from app.api.complete.async_endpoints import cancel_task

        mock_redis = MagicMock()

        async def mock_get(key: str) -> None:
            return None

        async def mock_close() -> None:
            pass

        mock_redis.get = mock_get
        mock_redis.close = mock_close

        stored: dict[str, Any] = {"status": "success"}

        with (
            patch("app.api.complete.async_endpoints.AsyncRedis") as mock_redis_cls,
            patch("app.api.complete.async_endpoints.get_task_result", new_callable=AsyncMock, return_value=stored),
        ):
            mock_redis_cls.from_url.return_value = mock_redis
            with pytest.raises(HTTPException) as exc_info:
                await cancel_task("task-done")
            assert exc_info.value.status_code == 409


class TestNonAgenticAsyncFallsThrough:
    def test_non_agentic_async_executes_sync(
        self, api_client: APITestClient, mock_db_session: MagicMock
    ) -> None:
        """async_execution=True with max_turns=1 and execute_tools=False executes synchronously."""
        agent = _mock_agent()

        mock_db_session_obj = MagicMock()
        mock_db_session_obj.id = "sess-test-456"
        mock_db_session_obj.status = "active"

        with (
            patch(f"{_ORCH}.validate_agent_slug", new_callable=AsyncMock),
            patch(f"{_ORCH}.validate_project_access"),
            patch(
                f"{_ORCH}.resolve_agent_and_model",
                new_callable=AsyncMock,
                return_value=(CLAUDE_SONNET, "claude", agent, None, "coder"),
            ),
            patch(
                f"{_ORCH}.apply_mention_override",
                return_value=(CLAUDE_SONNET, "claude"),
            ),
            patch(
                f"{_ORCH}.build_session_and_messages",
                new_callable=AsyncMock,
                return_value=(
                    False,  # is_agentic (max_turns=1, execute_tools=False)
                    "sess-test-456",  # session_id
                    mock_db_session_obj,  # session
                    True,  # is_new_session
                    [{"role": "user", "content": "hello"}],  # all_messages
                    [{"role": "user", "content": "hello"}],  # messages_dict
                    0,  # memory_facts
                    [],  # loaded_uuids
                    None,  # context_usage_info
                    None,  # cached
                ),
            ),
            patch(
                "app.services.project_budget.check_project_budget",
                new_callable=AsyncMock,
                return_value=_mock_budget_allowed(),
            ),
            patch(
                f"{_ORCH}.execute_and_respond",
                new_callable=AsyncMock,
                return_value=JSONResponse(content={"content": "sync response", "model": CLAUDE_SONNET}),
            ),
        ):
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
        agent = _mock_agent()

        mock_db_session_obj = MagicMock()
        mock_db_session_obj.id = "sess-test-789"
        mock_db_session_obj.status = "active"

        with (
            patch(f"{_ORCH}.validate_agent_slug", new_callable=AsyncMock),
            patch(f"{_ORCH}.validate_project_access"),
            patch(
                f"{_ORCH}.resolve_agent_and_model",
                new_callable=AsyncMock,
                return_value=(CLAUDE_SONNET, "claude", agent, None, "coder"),
            ),
            patch(
                f"{_ORCH}.apply_mention_override",
                return_value=(CLAUDE_SONNET, "claude"),
            ),
            patch(
                f"{_ORCH}.build_session_and_messages",
                new_callable=AsyncMock,
                return_value=(
                    True,  # is_agentic (max_turns=5, execute_tools=True)
                    "sess-test-789",  # session_id
                    mock_db_session_obj,  # session
                    True,  # is_new_session
                    [{"role": "user", "content": "Build something"}],  # all_messages
                    [{"role": "user", "content": "Build something"}],  # messages_dict
                    0,  # memory_facts
                    [],  # loaded_uuids
                    None,  # context_usage_info
                    None,  # cached
                ),
            ),
            patch(
                "app.services.project_budget.check_project_budget",
                new_callable=AsyncMock,
                return_value=_mock_budget_allowed(),
            ),
            patch(
                f"{_ORCH}.execute_and_respond",
                new_callable=AsyncMock,
                return_value=JSONResponse(content={"content": "agentic sync response", "status": "success"}),
            ),
        ):
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


class TestGetTaskStatusViaAPI:
    def test_get_status_endpoint_completed(
        self, api_client: APITestClient
    ) -> None:
        """GET /api/complete/tasks/{task_id} returns completed status."""
        stored: dict[str, Any] = {
            "task_id": "task-api-1",
            "content": "Result from worker",
            "model": CLAUDE_SONNET,
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

        with patch("app.api.complete.async_endpoints.get_task_result", new_callable=AsyncMock, return_value=stored):
            response = api_client.get("/api/complete/tasks/task-api-1")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"]["content"] == "Result from worker"

    def test_cancel_endpoint(self, api_client: APITestClient) -> None:
        """DELETE /api/complete/tasks/{task_id}/cancel cancels running task."""
        mock_redis = _mock_redis_client()
        mock_hatchet = MagicMock()
        mock_hatchet.runs.aio_cancel = AsyncMock()

        with (
            patch("app.api.complete.async_endpoints.AsyncRedis") as mock_redis_cls,
            patch("app.hatchet_app.hatchet", mock_hatchet),
        ):
            mock_redis_cls.from_url.return_value = mock_redis
            response = api_client.delete("/api/complete/tasks/task-cancel-1/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"
