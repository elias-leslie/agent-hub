"""Async task dispatch for completion API."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from app.adapters.base import Message
    from app.api.complete.schemas import CompletionRequest
    from app.services.agent_routing import ResolvedAgent

logger = logging.getLogger(__name__)


def _build_async_tools(request: CompletionRequest) -> list[dict[str, Any]] | None:
    """Build the serialised tools list for the workflow input."""
    if not request.tools:
        return None
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
            **(
                {"allowed_callers": t.allowed_callers}
                if t.allowed_callers != ["direct"]
                else {}
            ),
        }
        for t in request.tools
    ]


def _build_async_response_format(
    request: CompletionRequest,
) -> dict[str, Any] | None:
    """Build the serialised response_format for the workflow input."""
    if not request.response_format:
        return None
    return {
        "type": request.response_format.type,
        "schema": request.response_format.schema_,
    }


def _build_completion_kwargs(
    request: CompletionRequest,
    messages_dict: list[dict[str, Any]],
    resolved_model: str,
    provider: str,
    session_id: str,
    resolved_agent: ResolvedAgent | None,
    skip_cache: bool,
    client_id: str | None,
    request_source: str | None,
    task_id: str,
    thinking_level: str,
    async_tools: list[dict[str, Any]] | None,
    async_response_format: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return kwargs dict for CompletionInput construction."""
    return dict(
        task_id=task_id, messages=messages_dict, model=resolved_model,
        provider=provider, temperature=request.temperature,
        project_id=request.project_id, session_id=session_id,
        external_id=request.external_id, client_id=client_id,
        request_source=request_source, agent_slug=request.agent_slug,
        memory_group_id=request.memory_group_id,
        enable_caching=request.enable_caching, cache_ttl=request.cache_ttl,
        thinking_level=thinking_level, tools=async_tools,
        enable_programmatic_tools=request.enable_programmatic_tools,
        container_id=request.container_id, response_format=async_response_format,
        skip_cache=skip_cache, max_turns=request.max_turns,
        execute_tools=request.execute_tools, working_dir=request.working_dir,
        trace_id=request.trace_id, task_type=request.task_type,
        phase=request.phase,
        user_messages_for_db=(
            [m.model_dump() for m in request.messages] if request.messages else None
        ),
    )


def _build_workflow_input(
    request: CompletionRequest,
    messages_dict: list[dict[str, Any]],
    resolved_model: str,
    provider: str,
    session_id: str,
    resolved_agent: ResolvedAgent | None,
    skip_cache: bool,
    client_id: str | None,
    request_source: str | None,
    task_id: str,
    thinking_level: str,
    async_tools: list[dict[str, Any]] | None,
    async_response_format: dict[str, Any] | None,
) -> Any:
    """Construct and return the CompletionInput for the Hatchet workflow."""
    from app.workflows.completion import CompletionInput

    kwargs = _build_completion_kwargs(
        request, messages_dict, resolved_model, provider, session_id,
        resolved_agent, skip_cache, client_id, request_source, task_id,
        thinking_level, async_tools, async_response_format,
    )
    return CompletionInput(**kwargs)


async def _store_task_mapping(task_id: str, workflow_run_id: str) -> None:
    """Persist task_id -> workflow_run_id in Redis for cancel support."""
    from redis.asyncio import Redis as AsyncRedis

    from app.config import settings

    redis_client = AsyncRedis.from_url(settings.agent_hub_redis_url)
    try:
        await redis_client.setex(f"hatchet:run:{task_id}", 3600, workflow_run_id)
    finally:
        await redis_client.close()


async def _run_workflow_and_respond(
    request: CompletionRequest,
    wf_input: Any,
    task_id: str,
    session_id: str,
) -> JSONResponse:
    """Run the Hatchet workflow and return the accepted response."""
    from app.api.complete.schemas import AsyncTaskResponse
    from app.services.events import start_hatchet_stream_bridge
    from app.workflows.completion import completion_task

    ref = await completion_task.aio_run_no_wait(input=wf_input)
    workflow_run_id = ref.workflow_run_id

    await _store_task_mapping(task_id, workflow_run_id)
    await start_hatchet_stream_bridge(task_id, workflow_run_id)

    return JSONResponse(
        status_code=202,
        content=AsyncTaskResponse(
            task_id=task_id,
            session_id=session_id,
            status="pending",
            poll_url=f"/api/complete/tasks/{task_id}",
            events_channel=f"hatchet:stream:{workflow_run_id}",
            trace_id=request.trace_id,
        ).model_dump(),
    )


async def dispatch_async_completion(
    request: CompletionRequest,
    messages_dict: list[dict[str, Any]],
    resolved_model: str,
    provider: str,
    session_id: str,
    resolved_agent: ResolvedAgent | None,
    all_messages: list[Message],
    skip_cache: bool,
    client_id: str | None,
    request_source: str | None,
) -> JSONResponse:
    """Dispatch async completion to Hatchet workflow.

    Raises HTTPException(400) when stream mode is requested alongside
    async execution.  Returns a 202 JSONResponse with task/poll URLs.
    """
    if request.stream:
        raise HTTPException(
            status_code=400,
            detail="Cannot combine async_execution with stream mode.",
        )

    from app.api.complete.execution import get_thinking_level

    task_id = str(uuid.uuid4())
    thinking_level = get_thinking_level(request, all_messages, resolved_agent)
    async_tools = _build_async_tools(request)
    async_response_format = _build_async_response_format(request)

    wf_input = _build_workflow_input(
        request=request,
        messages_dict=messages_dict,
        resolved_model=resolved_model,
        provider=provider,
        session_id=session_id,
        resolved_agent=resolved_agent,
        skip_cache=skip_cache,
        client_id=client_id,
        request_source=request_source,
        task_id=task_id,
        thinking_level=thinking_level,
        async_tools=async_tools,
        async_response_format=async_response_format,
    )

    return await _run_workflow_and_respond(request, wf_input, task_id, session_id)
