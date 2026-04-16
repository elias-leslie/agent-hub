"""Canonical operator workflow endpoint."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete.complete_orchestrator import orchestrate_completion
from app.api.complete.schemas import CompletionRequest, CompletionResponse, MessageInput
from app.api.orchestration_models import (
    WorkflowRequest,
    WorkflowResponse,
    WorkflowStageName,
    WorkflowStageRequest,
    WorkflowStageResponse,
)
from app.db import get_db

router = APIRouter()

_STAGE_ORDER: tuple[WorkflowStageName, ...] = (
    "clarify",
    "plan",
    "execute",
    "review",
    "qa",
)
_DEFAULT_STAGE_AGENTS: dict[WorkflowStageName, str] = {
    "clarify": "chat",
    "plan": "planner",
    "execute": "coder",
    "review": "reviewer",
    "qa": "critic",
}
_DEFAULT_STAGE_PHASES: dict[WorkflowStageName, str] = {
    "clarify": "planning",
    "plan": "planning",
    "execute": "implementation",
    "review": "review",
    "qa": "review",
}


def _iter_stages(request: WorkflowRequest) -> Iterator[tuple[WorkflowStageName, WorkflowStageRequest]]:
    for stage_name in _STAGE_ORDER:
        stage = getattr(request, stage_name)
        if stage is not None:
            yield stage_name, stage


def _build_stage_message(
    request: WorkflowRequest,
    stage_name: WorkflowStageName,
    stage_results: dict[WorkflowStageName, CompletionResponse],
    stage: WorkflowStageRequest,
) -> str:
    sections: list[str] = []
    if request.shared_context:
        sections.append(f"Shared workflow context:\n{request.shared_context}")

    prior_outputs: list[str] = []
    for prior_stage in _STAGE_ORDER:
        if prior_stage == stage_name:
            break
        prior_result = stage_results.get(prior_stage)
        if prior_result is None:
            continue
        prior_outputs.append(f"{prior_stage.upper()} OUTPUT:\n{prior_result.content}")
    if prior_outputs:
        sections.append("Prior workflow outputs:\n\n" + "\n\n".join(prior_outputs))

    sections.append(f"Workflow stage: {stage_name}\n\n{stage.task}")
    return "\n\n".join(sections)


def _stage_identifier(value: str | None, stage_name: WorkflowStageName) -> str | None:
    if not value:
        return None
    return f"{value}:{stage_name}"


def _build_completion_request(
    request: WorkflowRequest,
    stage_name: WorkflowStageName,
    stage_results: dict[WorkflowStageName, CompletionResponse],
    stage: WorkflowStageRequest,
) -> CompletionRequest:
    return CompletionRequest(
        messages=[
            MessageInput(
                role="user",
                content=_build_stage_message(request, stage_name, stage_results, stage),
            )
        ],
        project_id=request.project_id,
        parent_session_id=request.parent_session_id,
        external_id=_stage_identifier(request.external_id, stage_name),
        trace_id=_stage_identifier(request.trace_id, stage_name),
        agent_slug=stage.agent_slug or _DEFAULT_STAGE_AGENTS[stage_name],
        task_type=stage.task_type,
        phase=stage.phase or _DEFAULT_STAGE_PHASES[stage_name],
        include_roles=stage.include_roles,
        response_format=stage.response_format,
        use_memory=stage.use_memory,
        execute_tools=stage.execute_tools,
        max_turns=stage.max_turns,
        working_dir=stage.working_dir,
        current_branch=stage.current_branch,
        thinking_level=stage.thinking_level,
        disable_agent_fallbacks=stage.disable_agent_fallbacks,
    )


@router.post("/workflow", response_model=WorkflowResponse)
async def execute_workflow(
    request: WorkflowRequest,
    http_request: Request,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> WorkflowResponse:
    """Run the canonical clarify -> plan -> execute -> review -> qa workflow."""

    stage_results: dict[WorkflowStageName, CompletionResponse] = {}
    completed_stages: list[WorkflowStageResponse] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for stage_name, stage in _iter_stages(request):
        completion_request = _build_completion_request(request, stage_name, stage_results, stage)
        response = await orchestrate_completion(completion_request, http_request, False, db)
        if not isinstance(response, CompletionResponse):
            raise HTTPException(
                status_code=500,
                detail=f"Workflow stage '{stage_name}' returned an unsupported response type.",
            )

        stage_results[stage_name] = response
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        completed_stages.append(
            WorkflowStageResponse(
                stage=stage_name,
                agent_used=response.agent_used or completion_request.agent_slug,
                content=response.content,
                model=response.model,
                provider=response.provider,
                session_id=response.session_id,
                usage=response.usage,
                context_usage=response.context_usage,
                output_usage=response.output_usage,
                finish_reason=response.finish_reason,
                memory_facts_injected=response.memory_facts_injected,
                fallback_used=response.fallback_used,
                fallback_reason=response.fallback_reason,
                cited_uuids=list(response.cited_uuids or []),
            )
        )

    return WorkflowResponse(
        status="completed",
        stages=completed_stages,
        final_output=completed_stages[-1].content,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
    )
