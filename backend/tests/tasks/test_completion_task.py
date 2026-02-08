"""Tests for the Celery agentic completion task."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.completion_task import _result_to_dict


@dataclass
class MockAgentProgress:
    turn: int = 1
    status: str = "complete"
    message: str = "done"
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    thinking: str | None = None


@dataclass
class MockCompletionInternalResult:
    content: str = "Final answer"
    model: str = "claude-sonnet-4-5"
    provider: str = "claude"
    input_tokens: int = 100
    output_tokens: int = 50
    finish_reason: str | None = "end_turn"
    session_id: str = "sess-123"
    memory_uuids: list[str] = field(default_factory=list)
    cited_uuids: list[str] = field(default_factory=list)
    from_cache: bool = False
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    turns: int = 3
    tool_calls_count: int = 5
    status: str = "success"
    error: str | None = None
    container_id: str | None = None
    progress_log: list[MockAgentProgress] = field(default_factory=list)


class TestResultToDict:
    def test_basic_mapping(self) -> None:
        result = MockCompletionInternalResult()
        d = _result_to_dict(result, "task-42")

        assert d["task_id"] == "task-42"
        assert d["content"] == "Final answer"
        assert d["model"] == "claude-sonnet-4-5"
        assert d["provider"] == "claude"
        assert d["input_tokens"] == 100
        assert d["output_tokens"] == 50
        assert d["turns"] == 3
        assert d["tool_calls_count"] == 5
        assert d["status"] == "success"

    def test_with_progress_log(self) -> None:
        result = MockCompletionInternalResult(
            progress_log=[
                MockAgentProgress(turn=1, status="turn_start", message="Starting turn 1"),
                MockAgentProgress(turn=1, status="complete", message="Done"),
            ]
        )
        d = _result_to_dict(result, "task-1")

        assert len(d["progress_log"]) == 2
        assert d["progress_log"][0]["turn"] == 1
        assert d["progress_log"][0]["status"] == "turn_start"

    def test_with_error(self) -> None:
        result = MockCompletionInternalResult(
            status="failed",
            error="Timeout exceeded",
        )
        d = _result_to_dict(result, "task-err")
        assert d["status"] == "failed"
        assert d["error"] == "Timeout exceeded"


class TestRunAgenticCompletion:
    @patch("app.tasks.completion_task.store_task_result")
    @patch("app.tasks.completion_task.CompletionEventPublisher")
    @patch("app.tasks.completion_task._run_completion")
    def test_publishes_lifecycle_events(
        self,
        mock_run: MagicMock,
        mock_publisher_cls: MagicMock,
        mock_store: MagicMock,
    ) -> None:
        from app.tasks.completion_task import run_agentic_completion

        mock_publisher = MagicMock()
        mock_publisher_cls.return_value = mock_publisher

        result_dict = {
            "task_id": "task-1",
            "content": "done",
            "turns": 2,
            "tool_calls_count": 3,
            "status": "success",
        }

        import asyncio

        future: asyncio.Future[dict[str, Any]] = asyncio.Future()
        future.set_result(result_dict)
        mock_run.return_value = future

        with patch("asyncio.new_event_loop") as mock_loop_factory:
            mock_loop = MagicMock()
            mock_loop.run_until_complete.return_value = result_dict
            mock_loop_factory.return_value = mock_loop

            run_agentic_completion(
                task_id="task-1",
                session_id="sess-1",
                messages=[{"role": "user", "content": "hello"}],
                model="claude-sonnet-4-5",
                provider="claude",
                temperature=1.0,
                project_id="test-project",
            )

        from app.services.completion_events import CompletionEventType

        calls = mock_publisher.publish.call_args_list
        event_types = [c[0][0] for c in calls]
        assert CompletionEventType.STARTED in event_types
        assert CompletionEventType.COMPLETED in event_types
        mock_publisher.close.assert_called_once()

    @patch("app.tasks.completion_task.store_task_result")
    @patch("app.tasks.completion_task.CompletionEventPublisher")
    def test_stores_result_on_success(
        self,
        mock_publisher_cls: MagicMock,
        mock_store: MagicMock,
    ) -> None:
        from app.tasks.completion_task import run_agentic_completion

        mock_publisher = MagicMock()
        mock_publisher_cls.return_value = mock_publisher

        result_dict = {"task_id": "task-1", "status": "success", "turns": 1, "tool_calls_count": 0}

        with patch("asyncio.new_event_loop") as mock_loop_factory:
            mock_loop = MagicMock()
            mock_loop.run_until_complete.return_value = result_dict
            mock_loop_factory.return_value = mock_loop

            run_agentic_completion(
                task_id="task-1",
                session_id="sess-1",
                messages=[],
                model="claude-sonnet-4-5",
                provider="claude",
                temperature=1.0,
                project_id="test-project",
            )

        mock_store.assert_called_once_with("task-1", result_dict)

    @patch("app.tasks.completion_task.store_task_result")
    @patch("app.tasks.completion_task.CompletionEventPublisher")
    def test_stores_error_on_failure(
        self,
        mock_publisher_cls: MagicMock,
        mock_store: MagicMock,
    ) -> None:
        from app.services.completion_events import CompletionEventType
        from app.tasks.completion_task import run_agentic_completion

        mock_publisher = MagicMock()
        mock_publisher_cls.return_value = mock_publisher

        with patch("asyncio.new_event_loop") as mock_loop_factory:
            mock_loop = MagicMock()
            mock_loop.run_until_complete.side_effect = RuntimeError("LLM exploded")
            mock_loop_factory.return_value = mock_loop

            with pytest.raises(RuntimeError, match="LLM exploded"):
                run_agentic_completion(
                    task_id="task-fail",
                    session_id="sess-1",
                    messages=[],
                    model="claude-sonnet-4-5",
                    provider="claude",
                    temperature=1.0,
                    project_id="test-project",
                )

        mock_store.assert_called_once()
        stored = mock_store.call_args[0][1]
        assert stored["status"] == "failed"
        assert "LLM exploded" in stored["error"]

        failed_calls = [c for c in mock_publisher.publish.call_args_list if c[0][0] == CompletionEventType.FAILED]
        assert len(failed_calls) == 1
        mock_publisher.close.assert_called_once()


class TestProgressCallback:
    @pytest.mark.asyncio
    async def test_progress_callback_maps_event_types(self) -> None:
        from app.services.completion_events import CompletionEventType

        mock_publisher = MagicMock()

        from app.api.complete.core import AgentProgress
        from app.tasks.completion_task import _run_completion

        progress_events: list[tuple[CompletionEventType, dict[str, Any]]] = []

        def capture_publish(event_type: CompletionEventType, data: dict[str, Any] | None = None) -> None:
            progress_events.append((event_type, data or {}))

        mock_publisher.publish = capture_publish

        mock_result = MockCompletionInternalResult()

        with patch("app.db.async_session") as mock_session_ctx:
            mock_db = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            async def mock_complete_internal(**kwargs: Any) -> MockCompletionInternalResult:
                cb = kwargs.get("progress_callback")
                if cb:
                    await cb(AgentProgress(turn=1, status="turn_start", message="Turn 1"))
                    await cb(AgentProgress(turn=1, status="tool_use", message="Using tool"))
                    await cb(AgentProgress(turn=1, status="tool_result", message="Got result"))
                    await cb(AgentProgress(turn=1, status="progress", message="Thinking..."))
                return mock_result

            with patch("app.api.complete.core.complete_internal", side_effect=mock_complete_internal):
                await _run_completion(
                    task_id="task-cb",
                    publisher=mock_publisher,
                    messages=[{"role": "user", "content": "hi"}],
                    model="claude-sonnet-4-5",
                    provider="claude",
                    temperature=1.0,
                    project_id="test-project",
                    session_id="sess-1",
                )

        event_types = [e[0] for e in progress_events]
        assert CompletionEventType.TURN_START in event_types
        assert CompletionEventType.TOOL_USE in event_types
        assert CompletionEventType.TOOL_RESULT in event_types
        assert CompletionEventType.PROGRESS in event_types
