"""Async task dispatch for completion API."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.api.complete.helpers import should_enable_thinking

if TYPE_CHECKING:
    from app.adapters.base import Message
    from app.api.complete.schemas import CompletionRequest
    from app.services.agent_routing import ResolvedAgent

logger = logging.getLogger(__name__)


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

    Args:
        request: Completion request
        messages_dict: Messages as dicts
        resolved_model: Resolved model name
        provider: Provider name
        session_id: Session ID
        resolved_agent: Resolved agent (if any)
        all_messages: All messages (for auto-thinking detection)
        skip_cache: Whether to skip cache
        client_id: Client ID
        request_source: Request source

    Returns:
        JSONResponse with task ID and status

    Raises:
        HTTPException: If validation fails
    """
    if request.stream:
        raise HTTPException(
            status_code=400,
            detail="Cannot combine async_execution with stream mode.",
        )

    from app.api.complete.schemas import AsyncTaskResponse
    from app.services.events import start_hatchet_stream_bridge
    from app.workflows.completion import CompletionInput, completion_task

    from app.api.complete.execution import get_thinking_level

    task_id = str(uuid.uuid4())
    thinking_level = get_thinking_level(request, all_messages, resolved_agent)

    async_tools: list[dict[str, Any]] | None = None
    if request.tools:
        async_tools = [
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

    async_response_format: dict[str, Any] | None = None
    if request.response_format:
        async_response_format = {
            "type": request.response_format.type,
            "schema": request.response_format.schema_,
        }

    wf_input = CompletionInput(
        task_id=task_id,
        messages=messages_dict,
        model=resolved_model,
        provider=provider,
        temperature=request.temperature,
        project_id=request.project_id,
        session_id=session_id,
        external_id=request.external_id,
        client_id=client_id,
        request_source=request_source,
        agent_slug=request.agent_slug,
        memory_group_id=request.memory_group_id,
        enable_caching=request.enable_caching,
        cache_ttl=request.cache_ttl,
        thinking_level=thinking_level,
        tools=async_tools,
        enable_programmatic_tools=request.enable_programmatic_tools,
        container_id=request.container_id,
        response_format=async_response_format,
        skip_cache=skip_cache,
        max_turns=request.max_turns,
        execute_tools=request.execute_tools,
        working_dir=request.working_dir,
        permission_config=request.permission_config.model_dump()
        if request.permission_config
        else (resolved_agent.agent.tool_permissions if resolved_agent else None),
        trace_id=request.trace_id,
        task_type=request.task_type,
        phase=request.phase,
        timeout_seconds=request.timeout_seconds,
        user_messages_for_db=[m.model_dump() for m in request.messages]
        if request.messages
        else None,
    )

    ref = await completion_task.aio_run_no_wait(input=wf_input)
    workflow_run_id = ref.workflow_run_id

    # Store task_id -> workflow_run_id mapping in Redis for cancel support
    from redis.asyncio import Redis as AsyncRedis

    from app.config import settings

    redis_client = AsyncRedis.from_url(settings.agent_hub_redis_url)
    try:
        await redis_client.setex(
            f"hatchet:run:{task_id}", 3600, workflow_run_id
        )
    finally:
        await redis_client.close()

    # Start stream bridge to forward Hatchet events to WebSocket
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
