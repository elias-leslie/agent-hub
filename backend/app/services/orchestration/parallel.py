"""Parallel execution for multi-agent tasks."""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from opentelemetry.trace import SpanKind

from app.services.telemetry import get_current_trace_id, get_tracer

from .parallel_helpers import (
    ParallelResult,
    ParallelTask,
    build_final_result,
    execute_all,
    execute_fail_fast,
)
from .subagent import SubagentConfig, SubagentManager, SubagentResult

logger = logging.getLogger(__name__)

__all__ = ["ParallelExecutor", "ParallelResult", "ParallelTask"]


class ParallelExecutor:
    """Execute multiple subagents in parallel with concurrency control."""

    def __init__(self, max_concurrency: int = 5):
        self._max_concurrency = max_concurrency
        self._subagent_manager = SubagentManager()
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def _execute_with_semaphore(
        self,
        task: ParallelTask,
        parent_id: str | None,
        trace_id: str | None,
        semaphore: asyncio.Semaphore | None = None,
    ) -> SubagentResult:
        """Execute a single task with concurrency control."""
        sem = semaphore or self._semaphore
        async with sem:
            return await self._subagent_manager.spawn(
                task=task.task,
                config=task.config,
                context=task.context,
                parent_id=parent_id,
                trace_id=trace_id,
            )

    async def _run_tasks(
        self,
        tasks: list[ParallelTask],
        overall_timeout: float | None,
        parent_id: str | None,
        trace_id: str | None,
        fail_fast: bool,
        semaphore: asyncio.Semaphore | None = None,
    ) -> list[SubagentResult]:
        """Build coroutines and dispatch to the appropriate execution strategy."""
        coros = [
            self._execute_with_semaphore(task, parent_id, trace_id, semaphore)
            for task in tasks
        ]
        if fail_fast:
            return await execute_fail_fast(coros, overall_timeout, parent_id, trace_id)
        return await execute_all(coros, overall_timeout, parent_id, trace_id)

    def _resolve_semaphore(
        self, max_concurrency: int | None
    ) -> tuple[int, asyncio.Semaphore | None]:
        """Return (effective_concurrency, per-request semaphore or None)."""
        effective = max_concurrency or self._max_concurrency
        sem = asyncio.Semaphore(effective) if max_concurrency else None
        return effective, sem

    async def _execute_in_span(
        self,
        tasks: list[ParallelTask],
        overall_timeout: float | None,
        parent_id: str | None,
        effective_trace_id: str | None,
        fail_fast: bool,
        request_semaphore: asyncio.Semaphore | None,
        started_at: datetime,
        span_attrs: dict[str, Any],
    ) -> ParallelResult:
        """Run tasks inside a tracing span and return the final result."""
        tracer = get_tracer("agent-hub.orchestration.parallel")
        with tracer.start_as_current_span(
            "parallel.execute", kind=SpanKind.INTERNAL, attributes=span_attrs
        ) as span:
            logger.info(
                f"Starting parallel execution of {len(tasks)} tasks "
                f"trace={effective_trace_id}"
            )
            results: list[SubagentResult] = []
            results = await self._run_tasks(
                tasks, overall_timeout, parent_id, effective_trace_id,
                fail_fast, semaphore=request_semaphore,
            )
            return build_final_result(
                results, len(tasks), started_at, effective_trace_id, span
            )

    async def execute(
        self,
        tasks: list[ParallelTask],
        overall_timeout: float | None = None,
        parent_id: str | None = None,
        trace_id: str | None = None,
        fail_fast: bool = False,
        max_concurrency: int | None = None,
    ) -> ParallelResult:
        """Execute multiple tasks in parallel.

        Args:
            max_concurrency: Per-request concurrency override. When set, creates
                a temporary semaphore instead of using the executor's default.
        """
        effective_trace_id = trace_id or get_current_trace_id()

        if not tasks:
            return ParallelResult(
                results=[],
                status="all_completed",
                completed_at=datetime.now(UTC),
                trace_id=effective_trace_id,
            )

        effective_concurrency, request_semaphore = self._resolve_semaphore(
            max_concurrency
        )
        started_at = datetime.now(UTC)
        span_attrs: dict[str, Any] = {
            "parallel.task_count": len(tasks),
            "parallel.max_concurrency": effective_concurrency,
            "parallel.timeout_requested": overall_timeout or 0,
            "parallel.fail_fast": fail_fast,
        }
        return await self._execute_in_span(
            tasks, overall_timeout, parent_id, effective_trace_id,
            fail_fast, request_semaphore, started_at, span_attrs,
        )

    async def map(
        self,
        task_template: str,
        items: list[Any],
        config: SubagentConfig,
        overall_timeout: float | None = None,
        trace_id: str | None = None,
    ) -> ParallelResult:
        """Map a task template over items in parallel."""
        tasks = [
            ParallelTask(
                task=task_template.format(item=item),
                config=replace(config, name=f"{config.name}_{i}"),
                id=str(i),
            )
            for i, item in enumerate(items)
        ]
        return await self.execute(tasks=tasks, overall_timeout=overall_timeout, trace_id=trace_id)
