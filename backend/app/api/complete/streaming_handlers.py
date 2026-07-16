"""Streaming request handling for completion API."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Literal, cast

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.api.complete.core import get_or_create_session, stream_completion
from app.api.complete.execution import get_thinking_level
from app.api.complete.request_setup import (
    apply_read_only_metadata,
    compact_context_if_needed,
)
from app.api.complete.tool_provisioner import provision_standard_tools
from app.services.agent_routing import inject_system_prompt_into_messages
from app.services.events import publish_session_start
from app.services.llm_messages import Message
from app.services.memory import inject_progressive_context, parse_memory_group_id
from app.services.memory.context_builder_settings import (
    memory_injection_enabled,
    resolve_memory_consumer_profile,
)
from app.services.memory.context_injector_ops import has_verified_canonical_context
from app.services.memory.context_resilience import (
    CanonicalContextInjectionFailed,
    build_unexpected_context_failure_notice,
    require_successful_context_injection,
)
from app.services.session_live_activity import mark_session_execution_start
from app.services.work_chats import bind_request_context

from .work_context import inject_work_context_message

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.api.complete.schemas import CompletionRequest
    from app.services.agent_routing import MandateInjection as AgentMandateInjection
    from app.services.agent_routing import ResolvedAgent

logger = logging.getLogger(__name__)


def _memory_block_len(progressive_context: object, field_name: str) -> int:
    """Return the size of a progressive-context block, tolerating legacy test doubles."""
    return len(getattr(progressive_context, field_name, []))


async def _setup_streaming_session(
    request: CompletionRequest,
    provider: str,
    resolved_model: str,
    resolved_agent: ResolvedAgent | None,
    db: AsyncSession | None,
    client_id: str | None,
    request_source: str | None,
) -> tuple[str, list[Message], bool]:
    """Set up or retrieve session and context messages for streaming.

    Returns:
        Tuple of (session_id, context_messages, is_new_session)
    """
    session_id = request.session_id or str(uuid.uuid4())
    context_messages: list[Message] = []
    is_new_session = False

    if db:
        stream_session, context_messages, is_new_session = await get_or_create_session(
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
            current_branch=request.current_branch,
            working_dir=request.working_dir,
            parent_session_id=request.parent_session_id,
            trace_id=request.trace_id,
        )
        session_id = stream_session.id
        apply_read_only_metadata(stream_session, request.read_only)
        await bind_request_context(
            db,
            session=stream_session,
            work_context=request.work_context,
            source_metadata=request.source_metadata,
        )
        mark_session_execution_start(stream_session)
        if is_new_session:
            await publish_session_start(session_id, resolved_model, request.project_id)
        await db.commit()

    return session_id, context_messages, is_new_session


def _build_streaming_messages(
    request: CompletionRequest,
    context_messages: list[Message],
    agent_mandate_injection: AgentMandateInjection | None,
) -> list[Message]:
    """Build base streaming messages before canonical/operator injection."""
    new_messages = [
        Message(role=cast(Literal["user", "assistant", "system"], m.role), content=m.content)
        for m in request.messages
    ]
    messages = context_messages + new_messages if context_messages else new_messages
    messages = inject_work_context_message(messages, request.work_context)

    return messages


async def _inject_streaming_memory(
    request: CompletionRequest,
    messages: list[Message],
    session_id: str,
    resolved_agent: ResolvedAgent | None,
    db: AsyncSession | None,
) -> list[Message]:
    """Inject memory context into streaming messages.

    Returns the updated messages list. Canonical failures abort before the
    streaming model call rather than silently dropping operator context.
    """
    agent_memory_config = resolved_agent.agent.memory_config if resolved_agent else None
    include_memories = request.use_memory and memory_injection_enabled(agent_memory_config)
    agentic_request = bool(resolved_agent) or request.max_turns > 1 or request.execute_tools
    include_prompts = agentic_request or (request.prompt_mode or "full") != "none"
    if not include_memories and not include_prompts:
        return messages

    messages_dict = [{"role": m.role, "content": m.content} for m in messages]
    scope, scope_id = parse_memory_group_id(request.memory_group_id)
    try:
        consumer_profile = resolve_memory_consumer_profile(agent_memory_config, surface="runtime")
        messages_dict, progressive_context = await inject_progressive_context(
            messages=messages_dict,
            scope=scope,
            scope_id=scope_id,
            variant=request.memory_variant_override,
            task_type=request.task_type,
            phase=request.phase,
            session_id=session_id,
            project_id=request.project_id,
            external_id=request.external_id,
            memory_config=agent_memory_config,
            current_branch=request.current_branch,
            consumer_profile=consumer_profile,
            consumer_agent_slug=resolved_agent.agent.slug if resolved_agent else None,
            consumer_surface="agent_runtime",
            include_prompts=include_prompts,
            include_memories=include_memories,
            db=db,
        )
        require_successful_context_injection(progressive_context)
        memory_facts_count = (
            _memory_block_len(progressive_context, "mandates")
            + _memory_block_len(progressive_context, "guardrails")
            + _memory_block_len(progressive_context, "reference_index")
            + _memory_block_len(progressive_context, "reference")
        )
        if memory_facts_count > 0:
            logger.info(
                f"Streaming: Injected {memory_facts_count} memory facts (scope={scope.value})"
            )
        return [
            Message(
                role=cast(Literal["user", "assistant", "system"], m["role"]),
                content=m["content"],
            )
            for m in messages_dict
        ]
    except CanonicalContextInjectionFailed:
        raise
    except Exception as e:
        logger.exception("Streaming canonical context injection failed unexpectedly")
        raise CanonicalContextInjectionFailed(
            build_unexpected_context_failure_notice(
                e,
                operation="streaming_completion_context_injection",
                consumer_profile=resolve_memory_consumer_profile(
                    agent_memory_config, surface="runtime"
                ),
                project_id=request.project_id or scope_id,
            )
        ) from e


async def _compact_streaming_context(
    messages: list[Message],
    resolved_model: str,
    session_id: str,
    db: AsyncSession | None,
) -> list[Message]:
    """Compact long resumed streaming context before execution."""
    if db is None:
        return messages

    messages_dict = [{"role": m.role, "content": m.content} for m in messages]
    compacted, was_compacted = await compact_context_if_needed(
        db,
        session_id,
        resolved_model,
        messages_dict,
    )
    if not was_compacted:
        return messages
    return [
        Message(
            role=cast(Literal["user", "assistant", "system"], m["role"]),
            content=m["content"],
        )
        for m in compacted
    ]


def _build_sse_response(
    messages: list[Message],
    resolved_model: str,
    provider: str,
    request: CompletionRequest,
    session_id: str,
    thinking_level: str | None,
    agent_used: str | None,
    model_used: str | None,
    fallback_used: bool,
    db: AsyncSession | None,
    is_new_session: bool,
    tools: list[dict[str, object]] | None,
    fallback_models: list[str] | None = None,
) -> StreamingResponse:
    """Construct the SSE StreamingResponse from a stream_completion generator."""
    source_metadata = (
        request.source_metadata.model_dump(exclude_none=True)
        if request.source_metadata is not None
        else None
    )
    return StreamingResponse(
        stream_completion(
            messages=messages,
            model=resolved_model,
            provider=provider,
            temperature=request.temperature,
            session_id=session_id,
            thinking_level=thinking_level,
            agent_used=agent_used,
            model_used=model_used,
            fallback_used=fallback_used,
            db=db,
            user_messages=request.messages,
            is_new_session=is_new_session,
            is_one_shot=not request.session_id,
            tools=tools,
            project_id=request.project_id,
            max_tool_turns=request.max_turns,
            working_dir=request.working_dir,
            source_metadata=source_metadata,
            fallback_models=fallback_models,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    """Handle a streaming completion request, returning an SSE StreamingResponse."""
    if request.async_execution:
        raise HTTPException(
            status_code=400,
            detail="Cannot combine async_execution with stream mode.",
        )

    session_id, context_messages, is_new_session = await _setup_streaming_session(
        request, provider, resolved_model, resolved_agent, db, client_id, request_source
    )
    messages = _build_streaming_messages(request, context_messages, agent_mandate_injection)
    messages = await _inject_streaming_memory(request, messages, session_id, resolved_agent, db)
    if agent_mandate_injection:
        messages = inject_system_prompt_into_messages(
            messages, agent_mandate_injection.system_content
        )
    messages = await _compact_streaming_context(messages, resolved_model, session_id, db)
    canonical_required = (
        bool(resolved_agent)
        or request.max_turns > 1
        or request.execute_tools
        or (request.prompt_mode or "full") != "none"
        or request.use_memory
    )
    if canonical_required and not has_verified_canonical_context(
        [{"role": message.role, "content": message.content} for message in messages]
    ):
        raise CanonicalContextInjectionFailed(
            "streaming completion requires a hash-verified Agent Hub canonical context envelope"
        )
    thinking_level = get_thinking_level(request, messages, resolved_agent)
    visible_tool_names = None
    if db and request.project_id:
        from app.services.project_permission_service import get_visible_tools_for_project

        visible_tool_names = await get_visible_tools_for_project(request.project_id, db)
    provisioned_tools = provision_standard_tools(
        request.execute_tools,
        None,
        agent_slug=agent_used,
        project_id=request.project_id,
        visible_tool_names=visible_tool_names,
    )
    tools = provisioned_tools.loaded_tools or None
    fallback_models: list[str] = []
    if resolved_agent is not None and not request.disable_agent_fallbacks:
        fallback_models.extend(resolved_agent.agent.fallback_models or [])
        escalation_model = resolved_agent.agent.escalation_model_id
        if escalation_model and escalation_model not in fallback_models:
            fallback_models.append(escalation_model)

    return _build_sse_response(
        messages, resolved_model, provider, request, session_id, thinking_level,
        agent_used, model_used, fallback_used,
        db, is_new_session, tools, fallback_models,
    )
