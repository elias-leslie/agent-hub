"""Helper utilities, types, and functions for parallel execution."""

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from opentelemetry.trace import Status, StatusCode

from app.services.llm_messages import Message

from .subagent import SubagentConfig, SubagentResult

logger = logging.getLogger(__name__)


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


def determine_status(
    completed: int, total: int
) -> Literal["all_completed", "partial", "all_failed", "timeout"]:
    """Determine overall status from completion counts."""
    if completed == total:
        return "all_completed"
    return "all_failed" if completed == 0 else "partial"


def exception_to_result(
    exc: Exception, parent_id: str | None, trace_id: str | None
) -> SubagentResult:
    """Convert exception to SubagentResult."""
    return SubagentResult(
        subagent_id="error",
        name="error",
        content="",
        status="error",
        provider="unknown",
        model="unknown",
        input_tokens=0,
        output_tokens=0,
        error=str(exc),
        parent_id=parent_id,
        trace_id=trace_id,
    )


def sum_tokens(results: list[SubagentResult]) -> tuple[int, int]:
    """Return (total_input_tokens, total_output_tokens) from results."""
    return (
        sum(r.input_tokens for r in results),
        sum(r.output_tokens for r in results),
    )


def _cancel_pending(pending: set[asyncio.Task[SubagentResult]]) -> None:
    """Cancel all pending tasks."""
    for task in pending:
        task.cancel()


async def _process_completed_batch(
    done: set[asyncio.Task[SubagentResult]],
    pending: set[asyncio.Task[SubagentResult]],
    results: list[SubagentResult],
) -> bool:
    """Process a batch of completed tasks; returns True if fail-fast should trigger."""
    for task in done:
        result = task.result()
        results.append(result)
        if result.status in ("error", "timeout"):
            _cancel_pending(pending)
            return True
    return False


async def execute_fail_fast(
    coros: list[Coroutine[Any, Any, SubagentResult]],
    timeout: float | None,
    parent_id: str | None,
    trace_id: str | None,
) -> list[SubagentResult]:
    """Execute with fail-fast mode: cancel remaining tasks on first error."""
    pending: set[asyncio.Task[SubagentResult]] = {
        asyncio.create_task(coro) for coro in coros
    }
    results: list[SubagentResult] = []
    try:
        async with asyncio.timeout(timeout):
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                if await _process_completed_batch(done, pending, results):
                    raise asyncio.CancelledError("Fail fast triggered")
    except TimeoutError:
        _cancel_pending(pending)
        raise
    return results


async def execute_all(
    coros: list[Coroutine[Any, Any, SubagentResult]],
    timeout: float | None,
    parent_id: str | None,
    trace_id: str | None,
) -> list[SubagentResult]:
    """Execute all tasks, collecting results including errors."""
    if timeout:
        raw_results = await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=True), timeout=timeout
        )
        return [
            r
            if isinstance(r, SubagentResult)
            else exception_to_result(Exception(str(r)), parent_id, trace_id)
            for r in raw_results
        ]
    return await asyncio.gather(*coros)


def annotate_span(
    results: list[SubagentResult],
    total_tasks: int,
    status: Literal["all_completed", "partial", "all_failed", "timeout"],
    total_input: int,
    total_output: int,
    span: Any,
) -> None:
    """Set OpenTelemetry span attributes and status."""
    completed_count = sum(1 for r in results if r.status == "completed")
    span.set_attribute("parallel.status", status)
    span.set_attribute("parallel.completed_count", completed_count)
    span.set_attribute("parallel.failed_count", total_tasks - completed_count)
    span.set_attribute("parallel.total_input_tokens", total_input)
    span.set_attribute("parallel.total_output_tokens", total_output)
    if status == "all_completed":
        span.set_status(Status(StatusCode.OK))
    else:
        desc = "Partial completion" if status == "partial" else "All tasks failed"
        span.set_status(Status(StatusCode.ERROR, desc))


def build_timeout_result(
    results: list[SubagentResult],
    started_at: datetime,
    trace_id: str | None,
    span: Any,
) -> ParallelResult:
    """Create a timeout ParallelResult and annotate the span."""
    span.set_attribute("parallel.status", "timeout")
    span.set_status(Status(StatusCode.ERROR, "Execution timed out"))
    total_input, total_output = sum_tokens(results)
    return ParallelResult(
        results=results,
        status="timeout",
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        trace_id=trace_id,
    )


def build_final_result(
    results: list[SubagentResult],
    total_tasks: int,
    started_at: datetime,
    trace_id: str | None,
    span: Any,
) -> ParallelResult:
    """Create the final ParallelResult, annotate span, and log summary."""
    completed_count = sum(1 for r in results if r.status == "completed")
    status = determine_status(completed_count, total_tasks)
    total_input, total_output = sum_tokens(results)
    annotate_span(results, total_tasks, status, total_input, total_output, span)
    logger.info(
        f"Parallel execution complete: {completed_count}/{total_tasks} succeeded, "
        f"tokens: {total_input}+{total_output}"
    )
    return ParallelResult(
        results=results,
        status=status,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        trace_id=trace_id,
    )
