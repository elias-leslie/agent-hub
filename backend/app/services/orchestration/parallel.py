"""Parallel execution for multi-agent tasks.

Enables running multiple subagents concurrently with configurable
concurrency limits and result aggregation.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from opentelemetry.trace import SpanKind, Status, StatusCode

from app.adapters.base import Message
from app.services.telemetry import get_current_trace_id, get_tracer

from .subagent import SubagentConfig, SubagentManager, SubagentResult

logger = logging.getLogger(__name__)


@dataclass
class ParallelTask:
    """A task to be executed in parallel."""

    task: str
    """Task description."""

    config: SubagentConfig
    """Subagent configuration."""

    context: list[Message] | None = None
    """Optional context messages."""

    id: str | None = None
    """Optional task ID for tracking."""


@dataclass
class ParallelResult:
    """Result from parallel execution."""

    results: list[SubagentResult]
    """Results from all subagents."""

    status: Literal["all_completed", "partial", "all_failed", "timeout"]
    """Overall execution status."""

    total_input_tokens: int = 0
    """Total input tokens across all subagents."""

    total_output_tokens: int = 0
    """Total output tokens across all subagents."""

    started_at: datetime = field(default_factory=datetime.now)
    """When execution started."""

    completed_at: datetime | None = None
    """When all tasks completed."""

    trace_id: str | None = None
    """OpenTelemetry trace ID for correlation."""

    @property
    def completed_count(self) -> int:
        """Number of successfully completed tasks."""
        return sum(1 for r in self.results if r.status == "completed")

    @property
    def failed_count(self) -> int:
        """Number of failed tasks."""
        return sum(1 for r in self.results if r.status in ("error", "timeout"))


class ParallelExecutor:
    """Execute multiple subagents in parallel.

    Features:
    - Configurable concurrency limits
    - Timeout per task and overall
    - Partial results on failure
    - Token tracking across all subagents
    """

    def __init__(
        self,
        max_concurrency: int = 5,
        default_timeout: float = 300.0,
    ):
        """Initialize parallel executor.

        Args:
            max_concurrency: Maximum concurrent subagents.
            default_timeout: Default timeout per task in seconds.
        """
        self._max_concurrency = max_concurrency
        self._default_timeout = default_timeout
        self._subagent_manager = SubagentManager()
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def _execute_with_semaphore(
        self,
        task: ParallelTask,
        parent_id: str | None,
        trace_id: str | None,
    ) -> SubagentResult:
        """Execute a single task with concurrency control."""
        async with self._semaphore:
            return await self._subagent_manager.spawn(
                task=task.task,
                config=task.config,
                context=task.context,
                parent_id=parent_id,
                trace_id=trace_id,
            )

    async def execute(
        self,
        tasks: list[ParallelTask],
        overall_timeout: float | None = None,
        parent_id: str | None = None,
        trace_id: str | None = None,
        fail_fast: bool = False,
    ) -> ParallelResult:
        """Execute multiple tasks in parallel.

        Args:
            tasks: List of tasks to execute.
            overall_timeout: Maximum total execution time.
            parent_id: Parent subagent ID for hierarchies.
            trace_id: OpenTelemetry trace ID.
            fail_fast: If True, cancel remaining on first failure.

        Returns:
            ParallelResult with all results.
        """
        # Use provided trace_id or get from current context
        effective_trace_id = trace_id or get_current_trace_id()

        if not tasks:
            return ParallelResult(
                results=[],
                status="all_completed",
                completed_at=datetime.now(),
                trace_id=effective_trace_id,
            )

        started_at = datetime.now()
        tracer = get_tracer("agent-hub.orchestration.parallel")

        with tracer.start_as_current_span(
            "parallel.execute",
            kind=SpanKind.INTERNAL,
            attributes={
                "parallel.task_count": len(tasks),
                "parallel.max_concurrency": self._max_concurrency,
                "parallel.timeout": overall_timeout or 0,
                "parallel.fail_fast": fail_fast,
            },
        ) as span:
            logger.info(
                f"Starting parallel execution of {len(tasks)} tasks trace={effective_trace_id}"
            )

            # Create coroutines for all tasks (use effective_trace_id for child spans)
            coros = [
                self._execute_with_semaphore(task, parent_id, effective_trace_id) for task in tasks
            ]

            results: list[SubagentResult] = []

            try:
                if fail_fast:
                    # Use as_completed to detect failures early
                    pending = set(asyncio.create_task(coro) for coro in coros)
                    done: set[asyncio.Task[SubagentResult]] = set()

                    try:
                        async with asyncio.timeout(overall_timeout):
                            while pending:
                                done_now, pending = await asyncio.wait(
                                    pending, return_when=asyncio.FIRST_COMPLETED
                                )
                                done.update(done_now)

                                for task in done_now:
                                    result = task.result()
                                    results.append(result)
                                    if result.status in ("error", "timeout") and fail_fast:
                                        # Cancel remaining
                                        for p in pending:
                                            p.cancel()
                                        raise asyncio.CancelledError("Fail fast triggered")
                    except TimeoutError:
                        # Cancel remaining on timeout
                        for p in pending:
                            p.cancel()
                else:
                    # Wait for all with timeout
                    if overall_timeout:
                        results = await asyncio.wait_for(
                            asyncio.gather(*coros, return_exceptions=True),
                            timeout=overall_timeout,
                        )
                        # Convert exceptions to error results
                        results = [
                            r
                            if isinstance(r, SubagentResult)
                            else SubagentResult(
                                subagent_id="error",
                                name="error",
                                content="",
                                status="error",
                                provider="unknown",
                                model="unknown",
                                input_tokens=0,
                                output_tokens=0,
                                error=str(r),
                                parent_id=parent_id,
                                trace_id=effective_trace_id,
                            )
                            for r in results
                        ]
                    else:
                        results = await asyncio.gather(*coros)

            except TimeoutError:
                logger.warning(f"Parallel execution timed out after {overall_timeout}s")
                span.set_attribute("parallel.status", "timeout")
                span.set_status(Status(StatusCode.ERROR, "Execution timed out"))
                return ParallelResult(
                    results=results,
                    status="timeout",
                    total_input_tokens=sum(r.input_tokens for r in results),
                    total_output_tokens=sum(r.output_tokens for r in results),
                    started_at=started_at,
                    completed_at=datetime.now(),
                    trace_id=effective_trace_id,
                )
            except asyncio.CancelledError:
                # Fail fast triggered
                pass

            # Determine overall status
            completed_count = sum(1 for r in results if r.status == "completed")
            if completed_count == len(tasks):
                status: Literal["all_completed", "partial", "all_failed", "timeout"] = (
                    "all_completed"
                )
            elif completed_count == 0:
                status = "all_failed"
            else:
                status = "partial"

            # Record metrics in span
            total_input = sum(r.input_tokens for r in results)
            total_output = sum(r.output_tokens for r in results)
            span.set_attribute("parallel.status", status)
            span.set_attribute("parallel.completed_count", completed_count)
            span.set_attribute("parallel.failed_count", len(tasks) - completed_count)
            span.set_attribute("parallel.total_input_tokens", total_input)
            span.set_attribute("parallel.total_output_tokens", total_output)

            if status == "all_completed":
                span.set_status(Status(StatusCode.OK))
            elif status == "partial":
                span.set_status(Status(StatusCode.ERROR, "Partial completion"))
            else:
                span.set_status(Status(StatusCode.ERROR, "All tasks failed"))

            result = ParallelResult(
                results=results,
                status=status,
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                started_at=started_at,
                completed_at=datetime.now(),
                trace_id=effective_trace_id,
            )

            logger.info(
                f"Parallel execution complete: {completed_count}/{len(tasks)} succeeded, "
                f"tokens: {result.total_input_tokens}+{result.total_output_tokens}"
            )

            return result

    async def map(
        self,
        task_template: str,
        items: list[Any],
        config: SubagentConfig,
        overall_timeout: float | None = None,
        trace_id: str | None = None,
    ) -> ParallelResult:
        """Map a task template over items in parallel.

        Convenience method that formats task_template with each item.

        Args:
            task_template: Template string with {item} placeholder.
            items: Items to process.
            config: Base configuration (cloned for each task).
            overall_timeout: Maximum total execution time.
            trace_id: OpenTelemetry trace ID.

        Returns:
            ParallelResult with all results.
        """
        tasks = [
            ParallelTask(
                task=task_template.format(item=item),
                config=SubagentConfig(
                    name=f"{config.name}_{i}",
                    provider=config.provider,
                    model=config.model,
                    system_prompt=config.system_prompt,
                    max_tokens=config.max_tokens,
                    temperature=config.temperature,
                    thinking_level=config.thinking_level,
                    tools=config.tools,
                    timeout_seconds=config.timeout_seconds,
                ),
                id=str(i),
            )
            for i, item in enumerate(items)
        ]

        return await self.execute(
            tasks=tasks,
            overall_timeout=overall_timeout,
            trace_id=trace_id,
        )
