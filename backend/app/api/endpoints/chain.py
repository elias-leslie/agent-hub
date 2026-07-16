"""Chain execution endpoints."""

from fastapi import APIRouter

from app.api.orchestration_models import (
    ChainRequest,
    ChainResponse,
    SubagentResponse,
)
from app.services.orchestration.chain import ChainExecutor, ChainStep
from app.services.orchestration.subagent import SubagentConfig
from app.services.telemetry import get_current_trace_id

router = APIRouter()

_chain_executor: ChainExecutor | None = None


def get_chain_executor() -> ChainExecutor:
    """Get or create chain executor singleton."""
    global _chain_executor
    if _chain_executor is None:
        _chain_executor = ChainExecutor()
    return _chain_executor


@router.post("/chain", response_model=ChainResponse)
async def execute_chain(request: ChainRequest) -> ChainResponse:
    """Execute subagent steps sequentially with context passing.

    Each step can reference the previous step's output using the
    ``{previous}`` placeholder in its task string.
    """
    executor = get_chain_executor()
    trace_id = get_current_trace_id()

    steps = [
        ChainStep(
            task=s.task,
            config=SubagentConfig(
                name=s.name,
                provider=s.provider,
                model=s.model,
                system_prompt=s.system_prompt,
                temperature=s.temperature,
                project_id=request.project_id,
                agent_slug=s.agent_slug,
            ),
            id=str(i),
        )
        for i, s in enumerate(request.steps)
    ]

    result = await executor.execute(
        steps=steps,
        overall_timeout=request.overall_timeout,
        trace_id=trace_id,
        stop_on_error=request.stop_on_error,
    )

    # Announce-back: store results in parent session if requested
    if request.parent_session_id:
        from app.api.endpoints.announce_back import announce_results_to_session

        await announce_results_to_session(request.parent_session_id, result.results)

    return ChainResponse(
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
        final_output=result.final_output,
        total_input_tokens=result.total_input_tokens,
        total_output_tokens=result.total_output_tokens,
        steps_completed=result.steps_completed,
        steps_total=result.steps_total,
        trace_id=result.trace_id,
    )
