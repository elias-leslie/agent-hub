"""Subagent spawning endpoints."""

from fastapi import APIRouter

from app.api.orchestration_models import SubagentRequest, SubagentResponse
from app.services.orchestration import SubagentConfig, SubagentManager
from app.services.telemetry import get_current_trace_id

router = APIRouter()

# Singleton manager
_subagent_manager: SubagentManager | None = None


def get_subagent_manager() -> SubagentManager:
    """Get or create subagent manager singleton."""
    global _subagent_manager
    if _subagent_manager is None:
        _subagent_manager = SubagentManager()
    return _subagent_manager


@router.post("/subagent", response_model=SubagentResponse)
async def spawn_subagent(request: SubagentRequest) -> SubagentResponse:
    """
    Spawn a subagent to handle a task.

    Creates an isolated context for the subagent with optional system prompt.
    """
    manager = get_subagent_manager()
    trace_id = get_current_trace_id()

    config = SubagentConfig(
        name=request.name,
        provider=request.provider,
        model=request.model,
        system_prompt=request.system_prompt,
        temperature=request.temperature,
        thinking_level=request.thinking_level,
        timeout_seconds=request.timeout_seconds,
    )

    result = await manager.spawn(
        task=request.task,
        config=config,
        trace_id=trace_id,
    )

    return SubagentResponse(
        subagent_id=result.subagent_id,
        name=result.name,
        content=result.content,
        status=result.status,
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        thinking_content=result.thinking_content,
        thinking_tokens=result.thinking_tokens,
        error=result.error,
        trace_id=result.trace_id,
    )
