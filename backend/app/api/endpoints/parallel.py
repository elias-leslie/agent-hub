"""Parallel execution endpoints."""

from fastapi import APIRouter

from app.api.orchestration_models import (
    ParallelRequest,
    ParallelResponse,
    SubagentResponse,
)
from app.services.orchestration import (
    ParallelExecutor,
    ParallelTask,
    SubagentConfig,
)
from app.services.telemetry import get_current_trace_id

router = APIRouter()

# Singleton executor
_parallel_executor: ParallelExecutor | None = None


def get_parallel_executor() -> ParallelExecutor:
    """Get or create parallel executor singleton."""
    global _parallel_executor
    if _parallel_executor is None:
        _parallel_executor = ParallelExecutor()
    return _parallel_executor


@router.post("/parallel", response_model=ParallelResponse)
async def execute_parallel(request: ParallelRequest) -> ParallelResponse:
    """
    Execute multiple subagents in parallel.

    Supports configurable concurrency and timeout.
    """
    executor = get_parallel_executor()
    trace_id = get_current_trace_id()

    tasks = [
        ParallelTask(
            task=t.task,
            config=SubagentConfig(
                name=t.name,
                provider=t.provider,
                model=t.model,
                system_prompt=t.system_prompt,
                temperature=t.temperature,
            ),
        )
        for t in request.tasks
    ]

    result = await executor.execute(
        tasks=tasks,
        overall_timeout=request.overall_timeout,
        trace_id=trace_id,
        fail_fast=request.fail_fast,
    )

    return ParallelResponse(
        status=result.status,
        results=[
            SubagentResponse(
                subagent_id=r.subagent_id,
                name=r.name,
                content=r.content,
                status=r.status,
                provider=r.provider,
                model=r.model,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                thinking_content=r.thinking_content,
                thinking_tokens=r.thinking_tokens,
                error=r.error,
                trace_id=r.trace_id,
            )
            for r in result.results
        ],
        total_input_tokens=result.total_input_tokens,
        total_output_tokens=result.total_output_tokens,
        completed_count=result.completed_count,
        failed_count=result.failed_count,
        trace_id=result.trace_id,
    )
