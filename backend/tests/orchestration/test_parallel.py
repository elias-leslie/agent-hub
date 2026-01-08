"""Tests for parallel execution."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.base import CompletionResult, Message
from app.services.orchestration.parallel import (
    ParallelExecutor,
    ParallelResult,
    ParallelTask,
)
from app.services.orchestration.subagent import SubagentConfig, SubagentResult


class TestParallelTask:
    """Tests for ParallelTask dataclass."""

    def test_basic_task(self):
        """Test basic task creation."""
        config = SubagentConfig(name="test")
        task = ParallelTask(task="Do something", config=config)

        assert task.task == "Do something"
        assert task.config.name == "test"
        assert task.context is None
        assert task.id is None

    def test_task_with_context(self):
        """Test task with context."""
        config = SubagentConfig(name="test")
        context = [Message(role="user", content="Previous")]
        task = ParallelTask(
            task="Do something",
            config=config,
            context=context,
            id="task-1",
        )

        assert task.context is not None
        assert len(task.context) == 1
        assert task.id == "task-1"


class TestParallelResult:
    """Tests for ParallelResult dataclass."""

    def test_all_completed(self):
        """Test all completed status."""
        results = [
            SubagentResult(
                subagent_id="1",
                name="test1",
                content="Result 1",
                status="completed",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=100,
                output_tokens=50,
            ),
            SubagentResult(
                subagent_id="2",
                name="test2",
                content="Result 2",
                status="completed",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=100,
                output_tokens=50,
            ),
        ]

        parallel_result = ParallelResult(
            results=results,
            status="all_completed",
            total_input_tokens=200,
            total_output_tokens=100,
        )

        assert parallel_result.completed_count == 2
        assert parallel_result.failed_count == 0

    def test_partial_completion(self):
        """Test partial completion status."""
        results = [
            SubagentResult(
                subagent_id="1",
                name="test1",
                content="Result 1",
                status="completed",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=100,
                output_tokens=50,
            ),
            SubagentResult(
                subagent_id="2",
                name="test2",
                content="",
                status="error",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=0,
                output_tokens=0,
                error="Failed",
            ),
        ]

        parallel_result = ParallelResult(
            results=results,
            status="partial",
            total_input_tokens=100,
            total_output_tokens=50,
        )

        assert parallel_result.completed_count == 1
        assert parallel_result.failed_count == 1


class TestParallelExecutor:
    """Tests for ParallelExecutor."""

    def test_initialization(self):
        """Test executor initialization."""
        executor = ParallelExecutor()
        assert executor._max_concurrency == 5
        assert executor._default_timeout == 300.0

    def test_custom_initialization(self):
        """Test custom executor configuration."""
        executor = ParallelExecutor(max_concurrency=10, default_timeout=60.0)
        assert executor._max_concurrency == 10
        assert executor._default_timeout == 60.0

    @pytest.mark.asyncio
    async def test_execute_empty_tasks(self):
        """Test executing with no tasks."""
        executor = ParallelExecutor()
        result = await executor.execute(tasks=[])

        assert result.status == "all_completed"
        assert len(result.results) == 0
        assert result.total_input_tokens == 0
        assert result.total_output_tokens == 0

    @pytest.mark.asyncio
    async def test_execute_single_task(self):
        """Test executing single task."""
        executor = ParallelExecutor()

        mock_result = CompletionResult(
            content="Single result",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=50,
        )

        with patch(
            "app.services.orchestration.subagent.SubagentManager.spawn",
            new=AsyncMock(
                return_value=SubagentResult(
                    subagent_id="test",
                    name="test",
                    content="Single result",
                    status="completed",
                    provider="claude",
                    model="claude-sonnet-4-5",
                    input_tokens=100,
                    output_tokens=50,
                )
            ),
        ):
            tasks = [
                ParallelTask(
                    task="Single task",
                    config=SubagentConfig(name="test"),
                )
            ]

            result = await executor.execute(tasks=tasks)

            assert result.status == "all_completed"
            assert len(result.results) == 1
            assert result.results[0].content == "Single result"

    @pytest.mark.asyncio
    async def test_execute_multiple_tasks(self):
        """Test executing multiple tasks in parallel."""
        executor = ParallelExecutor()

        call_count = 0

        async def mock_spawn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return SubagentResult(
                subagent_id=f"test-{call_count}",
                name=f"test-{call_count}",
                content=f"Result {call_count}",
                status="completed",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=100,
                output_tokens=50,
            )

        with patch(
            "app.services.orchestration.subagent.SubagentManager.spawn",
            new=mock_spawn,
        ):
            tasks = [
                ParallelTask(
                    task=f"Task {i}",
                    config=SubagentConfig(name=f"test-{i}"),
                )
                for i in range(3)
            ]

            result = await executor.execute(tasks=tasks)

            assert result.status == "all_completed"
            assert len(result.results) == 3
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_execute_with_failure(self):
        """Test execution with some failures."""
        executor = ParallelExecutor()

        call_count = 0

        async def mock_spawn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return SubagentResult(
                    subagent_id=f"test-{call_count}",
                    name=f"test-{call_count}",
                    content="",
                    status="error",
                    provider="claude",
                    model="claude-sonnet-4-5",
                    input_tokens=0,
                    output_tokens=0,
                    error="Failed",
                )
            return SubagentResult(
                subagent_id=f"test-{call_count}",
                name=f"test-{call_count}",
                content=f"Result {call_count}",
                status="completed",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=100,
                output_tokens=50,
            )

        with patch(
            "app.services.orchestration.subagent.SubagentManager.spawn",
            new=mock_spawn,
        ):
            tasks = [
                ParallelTask(
                    task=f"Task {i}",
                    config=SubagentConfig(name=f"test-{i}"),
                )
                for i in range(3)
            ]

            result = await executor.execute(tasks=tasks)

            assert result.status == "partial"
            assert result.completed_count == 2
            assert result.failed_count == 1

    @pytest.mark.asyncio
    async def test_execute_with_trace_id(self):
        """Test execution with trace ID propagation."""
        executor = ParallelExecutor()

        trace_ids = []

        async def mock_spawn(*args, **kwargs):
            trace_ids.append(kwargs.get("trace_id"))
            return SubagentResult(
                subagent_id="test",
                name="test",
                content="Result",
                status="completed",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=100,
                output_tokens=50,
                trace_id=kwargs.get("trace_id"),
            )

        with patch(
            "app.services.orchestration.subagent.SubagentManager.spawn",
            new=mock_spawn,
        ):
            tasks = [
                ParallelTask(
                    task=f"Task {i}",
                    config=SubagentConfig(name=f"test-{i}"),
                )
                for i in range(2)
            ]

            result = await executor.execute(tasks=tasks, trace_id="test-trace")

            assert result.trace_id == "test-trace"
            # All spawns should have received the trace ID
            assert all(t == "test-trace" for t in trace_ids)

    @pytest.mark.asyncio
    async def test_map_function(self):
        """Test map function for processing items."""
        executor = ParallelExecutor()

        async def mock_spawn(*args, **kwargs):
            task = kwargs.get("task") or args[0]
            return SubagentResult(
                subagent_id="test",
                name="test",
                content=f"Processed: {task}",
                status="completed",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=100,
                output_tokens=50,
            )

        with patch(
            "app.services.orchestration.subagent.SubagentManager.spawn",
            new=mock_spawn,
        ):
            items = ["apple", "banana", "cherry"]
            config = SubagentConfig(name="processor")

            result = await executor.map(
                task_template="Process this fruit: {item}",
                items=items,
                config=config,
            )

            assert result.status == "all_completed"
            assert len(result.results) == 3

    @pytest.mark.asyncio
    async def test_concurrency_limit(self):
        """Test that concurrency is limited."""
        import asyncio

        executor = ParallelExecutor(max_concurrency=2)
        concurrent_count = 0
        max_concurrent = 0

        async def mock_spawn(*args, **kwargs):
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.1)
            concurrent_count -= 1
            return SubagentResult(
                subagent_id="test",
                name="test",
                content="Result",
                status="completed",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=100,
                output_tokens=50,
            )

        with patch(
            "app.services.orchestration.subagent.SubagentManager.spawn",
            new=mock_spawn,
        ):
            tasks = [
                ParallelTask(
                    task=f"Task {i}",
                    config=SubagentConfig(name=f"test-{i}"),
                )
                for i in range(5)
            ]

            result = await executor.execute(tasks=tasks)

            assert result.status == "all_completed"
            assert max_concurrent <= 2  # Should never exceed concurrency limit

    @pytest.mark.asyncio
    async def test_execute_fail_fast(self):
        """Test fail-fast mode cancels remaining tasks on first failure."""
        executor = ParallelExecutor()

        call_count = 0

        async def mock_spawn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return SubagentResult(
                    subagent_id="fail",
                    name="fail",
                    content="",
                    status="error",
                    provider="claude",
                    model="claude-sonnet-4-5",
                    input_tokens=0,
                    output_tokens=0,
                    error="Failed",
                )
            return SubagentResult(
                subagent_id=f"test-{call_count}",
                name=f"test-{call_count}",
                content="Result",
                status="completed",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=100,
                output_tokens=50,
            )

        with patch(
            "app.services.orchestration.subagent.SubagentManager.spawn",
            new=mock_spawn,
        ):
            tasks = [
                ParallelTask(
                    task=f"Task {i}",
                    config=SubagentConfig(name=f"test-{i}"),
                )
                for i in range(5)
            ]

            result = await executor.execute(tasks=tasks, fail_fast=True)

            # Should have partial results
            assert result.status in ("partial", "all_failed")

    @pytest.mark.asyncio
    async def test_execute_with_timeout(self):
        """Test execution with overall timeout."""
        import asyncio

        executor = ParallelExecutor()

        async def slow_spawn(*args, **kwargs):
            await asyncio.sleep(10)  # Very slow
            return SubagentResult(
                subagent_id="test",
                name="test",
                content="Result",
                status="completed",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=100,
                output_tokens=50,
            )

        with patch(
            "app.services.orchestration.subagent.SubagentManager.spawn",
            new=slow_spawn,
        ):
            tasks = [
                ParallelTask(
                    task="Slow task",
                    config=SubagentConfig(name="slow"),
                )
            ]

            result = await executor.execute(tasks=tasks, overall_timeout=0.1)

            # Should timeout
            assert result.status == "timeout"
