"""Streaming request handling for completion API."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Literal, cast

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.adapters.base import Message
from app.api.complete.core import get_or_create_session, stream_completion
from app.services.agent_routing import inject_system_prompt_into_messages
from app.services.events import publish_session_start
from app.services.memory import inject_progressive_context, parse_memory_group_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.api.complete.schemas import CompletionRequest
    from app.services.agent_routing import MandateInjection as AgentMandateInjection
    from app.services.agent_routing import ResolvedAgent

logger = logging.getLogger(__name__)


async def handle_streaming_request(
    request: CompletionRequest,
    resolved_model: str,
    provider: str,
    resolved_agent: ResolvedAgent | None,
    agent_mandate_injection: AgentMandateInjection | None,
    agent_used: str | None,
    model_used: str | None,
    fallback_used: bool,
    db: AsyncSession | None,
    client_id: str | None,
    request_source: str | None,
) -> StreamingResponse:
    """Handle streaming completion request.

    Args:
        request: Completion request
        resolved_model: Resolved model name
        provider: Provider name
        resolved_agent: Resolved agent (if any)
        agent_mandate_injection: Agent mandate injection (if any)
        agent_used: Agent slug used
        model_used: Model used
        fallback_used: Whether fallback was used
        db: Database session
        client_id: Client ID
        request_source: Request source

    Returns:
        StreamingResponse with SSE stream

    Raises:
        HTTPException: If validation fails
    """
    if request.async_execution:
        raise HTTPException(
            status_code=400,
            detail="Cannot combine async_execution with stream mode.",
        )

    session_id = request.session_id or str(uuid.uuid4())
    stream_context_messages: list[Message] = []
    is_new_session = False

    if db:
        stream_session, stream_context_messages, is_new_session = await get_or_create_session(
            db,
            request.session_id,
            request.project_id,
            provider,
            resolved_model,
            session_type="chat",
            external_id=request.external_id,
            client_id=client_id,
            request_source=request_source,
            agent_slug=request.agent_slug,
        )
        session_id = stream_session.id
        if is_new_session:
            await publish_session_start(session_id, resolved_model, request.project_id)

    new_messages = [
        Message(role=cast(Literal["user", "assistant", "system"], m.role), content=m.content)
        for m in request.messages
    ]
    messages_for_streaming = (
        stream_context_messages + new_messages if stream_context_messages else new_messages
    )

    if agent_mandate_injection:
        messages_for_streaming = inject_system_prompt_into_messages(
            messages_for_streaming, agent_mandate_injection.system_content
        )

    # Inject memory context for streaming requests
    if request.use_memory:
        messages_dict_for_memory = [
            {"role": m.role, "content": m.content} for m in messages_for_streaming
        ]
        scope, scope_id = parse_memory_group_id(request.memory_group_id)
        try:
            stream_agent_memory_config = (
                resolved_agent.agent.memory_config if resolved_agent else None
            )
            messages_dict_for_memory, progressive_context = await inject_progressive_context(
                messages=messages_dict_for_memory,
                scope=scope,
                scope_id=scope_id,
                task_type=request.task_type,
                phase=request.phase,
                session_id=session_id,
                project_id=request.project_id,
                external_id=request.external_id,
                memory_config=stream_agent_memory_config,
                current_branch=request.current_branch,
            )
            memory_facts_count = (
                len(progressive_context.mandates)
                + len(progressive_context.guardrails)
                + len(progressive_context.reference)
            )
            if memory_facts_count > 0:
                logger.info(
                    f"Streaming: Injected {memory_facts_count} memory facts (scope={scope.value})"
                )
            # Rebuild messages_for_streaming from injected dict
            messages_for_streaming = [
                Message(
                    role=cast(Literal["user", "assistant", "system"], m["role"]),
                    content=m["content"],
                )
                for m in messages_dict_for_memory
            ]
        except Exception as e:
            logger.warning(f"Streaming: Memory injection failed (continuing without): {e}")

    return StreamingResponse(
        stream_completion(
            messages=messages_for_streaming,
            model=resolved_model,
            provider=provider,
            temperature=request.temperature,
            session_id=session_id,
            agent_used=agent_used,
            model_used=model_used,
            fallback_used=fallback_used,
            db=db,
            user_messages=request.messages,
            is_new_session=is_new_session,
            is_one_shot=not request.session_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
