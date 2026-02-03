"""Parallel execution for multi-agent tasks."""

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from opentelemetry.trace import SpanKind, Status, StatusCode

from app.adapters.base import Message
from app.services.telemetry import get_current_trace_id, get_tracer

from .subagent import SubagentConfig, SubagentManager, SubagentResult

logger = logging.getLogger(__name__)


def _determine_status(completed: int, total: int) -> Literal["all_completed", "partial", "all_failed", "timeout"]:
    """Determine overall status from completion counts."""
    if completed == total:
        return "all_completed"
    return "all_failed" if completed == 0 else "partial"


def _exception_to_result(exc: Exception, parent_id: str | None, trace_id: str | None) -> SubagentResult:
    """Convert exception to SubagentResult."""
    return SubagentResult(
        subagent_id="error", name="error", content="", status="error", provider="unknown", model="unknown",
        input_tokens=0, output_tokens=0, error=str(exc), parent_id=parent_id, trace_id=trace_id
    )


@dataclass
class ParallelTask:
    """A task to be executed in parallel."""

    task: str
    config: SubagentConfig
    context: list[Message] | None = None
    id: str | None = None


@dataclass
class ParallelResult:
    """Result from parallel execution."""

    results: list[SubagentResult]
    status: Literal["all_completed", "partial", "all_failed", "timeout"]
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    trace_id: str | None = None

    @property
    def completed_count(self) -> int:
        return sum(1 for r in self.results if r.status == "completed")

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.status in ("error", "timeout"))


class ParallelExecutor:
    """Execute multiple subagents in parallel with concurrency control."""

    def __init__(self, max_concurrency: int = 5, default_timeout: float = 300.0):
        self._max_concurrency = max_concurrency
        self._default_timeout = default_timeout
        self._subagent_manager = SubagentManager()
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def _execute_with_semaphore(self, task: ParallelTask, parent_id: str | None, trace_id: str | None) -> SubagentResult:
        """Execute a single task with concurrency control."""
        async with self._semaphore:
            return await self._subagent_manager.spawn(
                task=task.task, config=task.config, context=task.context, parent_id=parent_id, trace_id=trace_id
            )

    async def _execute_fail_fast(
        self, coros: list[Coroutine[Any, Any, SubagentResult]], timeout: float | None, parent_id: str | None, trace_id: str | None
    ) -> list[SubagentResult]:
        """Execute with fail-fast mode."""
        pending = set(asyncio.create_task(coro) for coro in coros)
        results: list[SubagentResult] = []

        try:
            async with asyncio.timeout(timeout):
                while pending:
                    done_now, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done_now:
                        result = task.result()
                        results.append(result)
                        if result.status in ("error", "timeout"):
                            for p in pending:
                                p.cancel()
                            raise asyncio.CancelledError("Fail fast triggered")
        except TimeoutError:
            for p in pending:
                p.cancel()
            raise
        return results

    async def _execute_all(
        self, coros: list[Coroutine[Any, Any, SubagentResult]], timeout: float | None, parent_id: str | None, trace_id: str | None
    ) -> list[SubagentResult]:
        """Execute all tasks, collecting results."""
        if timeout:
            raw_results = await asyncio.wait_for(asyncio.gather(*coros, return_exceptions=True), timeout=timeout)
            return [r if isinstance(r, SubagentResult) else _exception_to_result(Exception(str(r)), parent_id, trace_id) for r in raw_results]
        return await asyncio.gather(*coros)

    def _create_timeout_result(self, results: list[SubagentResult], started_at: datetime, trace_id: str | None, span: Any) -> ParallelResult:
        """Create timeout result."""
        span.set_attribute("parallel.status", "timeout")
        span.set_status(Status(StatusCode.ERROR, "Execution timed out"))
        return ParallelResult(
            results=results, status="timeout", total_input_tokens=sum(r.input_tokens for r in results),
            total_output_tokens=sum(r.output_tokens for r in results), started_at=started_at,
            completed_at=datetime.now(UTC), trace_id=trace_id
        )

    def _create_result(self, results: list[SubagentResult], total_tasks: int, started_at: datetime, trace_id: str | None, span: Any) -> ParallelResult:
        """Create final result with metrics."""
        completed_count = sum(1 for r in results if r.status == "completed")
        status = _determine_status(completed_count, total_tasks)
        total_input, total_output = sum(r.input_tokens for r in results), sum(r.output_tokens for r in results)

        span.set_attribute("parallel.status", status)
        span.set_attribute("parallel.completed_count", completed_count)
        span.set_attribute("parallel.failed_count", total_tasks - completed_count)
        span.set_attribute("parallel.total_input_tokens", total_input)
        span.set_attribute("parallel.total_output_tokens", total_output)
        span.set_status(Status(StatusCode.OK) if status == "all_completed" else Status(StatusCode.ERROR, "Partial completion" if status == "partial" else "All tasks failed"))

        logger.info(f"Parallel execution complete: {completed_count}/{total_tasks} succeeded, tokens: {total_input}+{total_output}")

        return ParallelResult(
            results=results, status=status, total_input_tokens=total_input, total_output_tokens=total_output,
            started_at=started_at, completed_at=datetime.now(UTC), trace_id=trace_id
        )

    async def execute(
        self, tasks: list[ParallelTask], overall_timeout: float | None = None, parent_id: str | None = None,
        trace_id: str | None = None, fail_fast: bool = False
    ) -> ParallelResult:
        """Execute multiple tasks in parallel."""
        effective_trace_id = trace_id or get_current_trace_id()

        if not tasks:
            return ParallelResult(results=[], status="all_completed", completed_at=datetime.now(UTC), trace_id=effective_trace_id)

        started_at = datetime.now(UTC)
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
            logger.info(f"Starting parallel execution of {len(tasks)} tasks trace={effective_trace_id}")

            coros = [self._execute_with_semaphore(task, parent_id, effective_trace_id) for task in tasks]
            results: list[SubagentResult] = []

            try:
                if fail_fast:
                    results = await self._execute_fail_fast(coros, overall_timeout, parent_id, effective_trace_id)
                else:
                    results = await self._execute_all(coros, overall_timeout, parent_id, effective_trace_id)
            except TimeoutError:
                logger.warning(f"Parallel execution timed out after {overall_timeout}s")
                return self._create_timeout_result(results, started_at, effective_trace_id, span)
            except asyncio.CancelledError:
                pass

            return self._create_result(results, len(tasks), started_at, effective_trace_id, span)

    async def map(
        self, task_template: str, items: list[Any], config: SubagentConfig,
        overall_timeout: float | None = None, trace_id: str | None = None
    ) -> ParallelResult:
        """Map a task template over items in parallel."""
        from dataclasses import replace

        tasks = [
            ParallelTask(task=task_template.format(item=item), config=replace(config, name=f"{config.name}_{i}"), id=str(i))
            for i, item in enumerate(items)
        ]
        return await self.execute(tasks=tasks, overall_timeout=overall_timeout, trace_id=trace_id)
