"""Core completion logic for the completion API."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters.base import Message
from app.models import Session as DBSession
from app.models import SessionEventType
from app.services.context_tracker import log_token_usage
from app.services.event_storage import (
    get_sequencer,
    store_memory_cite_event,
    store_memory_inject_event,
    store_message_event,
    store_thinking_event,
    store_tool_result_event,
    store_tool_use_event,
)
from app.services.events import (
    publish_complete,
    publish_message,
    publish_session_start,
)
from app.services.memory import (
    extract_uuid_prefixes,
    inject_progressive_context,
    parse_memory_group_id,
    resolve_full_uuids,
    track_loaded_batch,
    track_referenced_batch,
)
from app.services.response_cache import get_response_cache
from app.services.token_counter import estimate_cost

from .helpers import (
    get_adapter,
    is_error_response,
    normalize_content_for_storage,
)
from .schemas import MessageInput, StreamingChunk

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class CompletionInternalResult:
    """Result from complete_internal() for completion operations."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None
    session_id: str
    memory_uuids: list[str]
    cited_uuids: list[str]
    from_cache: bool = False
    cache_metrics: Any | None = None
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    tool_calls: list[Any] | None = None
    container: Any | None = None


async def get_or_create_session(
    db: AsyncSession,
    session_id: str | None,
    project_id: str,
    provider: str,
    model: str,
    session_type: str = "completion",
    external_id: str | None = None,
    client_id: str | None = None,
    request_source: str | None = None,
    agent_slug: str | None = None,
) -> tuple[DBSession, list[Message], bool]:
    """Get existing session or create new one. Returns (session, messages, is_new)."""
    if session_id:
        result = await db.execute(
            select(DBSession)
            .options(selectinload(DBSession.events))
            .where(DBSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session:
            models_used = session.models_used or []
            providers_used = session.providers_used or []
            if model not in models_used:
                models_used.append(model)
                session.models_used = models_used
            if provider not in providers_used:
                providers_used.append(provider)
                session.providers_used = providers_used
            if agent_slug and not session.agent_slug:
                session.agent_slug = agent_slug
            await db.commit()

            context_messages = [
                Message(role=e.role, content=e.content)
                for e in sorted(session.events, key=lambda x: (x.turn, x.sequence))
                if e.event_type
                in (
                    SessionEventType.USER_MESSAGE,
                    SessionEventType.ASSISTANT_MESSAGE,
                    SessionEventType.SYSTEM_MESSAGE,
                )
                and e.role
                and e.content
            ]

            max_turn = max((e.turn for e in session.events), default=0)
            if max_turn > 0:
                get_sequencer().set_turn(session.id, max_turn + 1)

            return session, context_messages, False

    new_session_id = session_id or str(uuid.uuid4())
    session = DBSession(
        id=new_session_id,
        project_id=project_id,
        provider=provider,
        model=model,
        status="active",
        session_type=session_type,
        external_id=external_id,
        client_id=client_id,
        request_source=request_source,
        agent_slug=agent_slug,
        models_used=[model],
        providers_used=[provider],
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session, [], True


async def save_events(
    db: AsyncSession,
    session_id: str,
    user_messages: list[MessageInput],
    assistant_content: str,
    input_tokens: int,
    output_tokens: int,
    model_used: str | None = None,
    thinking_content: str | None = None,
    thinking_tokens: int | None = None,
) -> None:
    """Save user messages, thinking, and assistant response as events."""
    for msg in user_messages:
        if msg.role in ("user", "system"):
            await store_message_event(
                db=db,
                session_id=session_id,
                role=msg.role,
                content=normalize_content_for_storage(msg.content),
            )

    if thinking_content:
        await store_thinking_event(
            db=db,
            session_id=session_id,
            thinking_content=thinking_content,
            tokens=thinking_tokens,
            model_used=model_used,
        )

    await store_message_event(
        db=db,
        session_id=session_id,
        role="assistant",
        content=assistant_content,
        tokens=output_tokens,
        model_used=model_used,
    )
    await db.commit()


async def update_provider_metadata(
    db: AsyncSession,
    session: DBSession,
    cache_metrics: dict[str, Any] | None,
) -> None:
    """Update session with provider-specific metadata like cache info."""
    if not cache_metrics:
        return

    # Merge with existing metadata
    existing = session.provider_metadata or {}
    existing["cache"] = {
        "last_cache_creation_tokens": cache_metrics.get("cache_creation_input_tokens", 0),
        "last_cache_read_tokens": cache_metrics.get("cache_read_input_tokens", 0),
        "total_cache_creation_tokens": existing.get("cache", {}).get(
            "total_cache_creation_tokens", 0
        )
        + cache_metrics.get("cache_creation_input_tokens", 0),
        "total_cache_read_tokens": existing.get("cache", {}).get("total_cache_read_tokens", 0)
        + cache_metrics.get("cache_read_input_tokens", 0),
    }
    session.provider_metadata = existing
    await db.commit()


async def complete_internal(
    messages: list[dict[str, Any]],
    model: str,
    provider: str,
    temperature: float,
    project_id: str,
    db: AsyncSession,
    session_id: str | None = None,
    external_id: str | None = None,
    client_id: str | None = None,
    request_source: str | None = None,
    agent_slug: str | None = None,
    use_memory: bool = False,
    memory_group_id: str | None = None,
    enable_caching: bool = True,
    cache_ttl: str = "ephemeral",
    thinking_level: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    enable_programmatic_tools: bool = False,
    container_id: str | None = None,
    response_format: dict[str, Any] | None = None,
    skip_cache: bool = False,
    user_messages_for_db: list[MessageInput] | None = None,
) -> CompletionInternalResult:
    """Core completion logic for /complete endpoint.

    Args:
        messages: Conversation messages as dicts with role/content
        model: Model identifier
        provider: Provider name (claude/gemini/openai)
        temperature: Sampling temperature
        project_id: Project ID for session tracking
        db: Database session
        session_id: Optional existing session ID (creates new if None)
        external_id: External ID for cost aggregation
        client_id: Client identifier
        request_source: Request source
        agent_slug: Agent slug for metrics attribution
        use_memory: Whether to inject memory context
        memory_group_id: Memory group for isolation
        enable_caching: Enable prompt caching
        cache_ttl: Cache TTL
        thinking_level: Extended thinking level
        tools: Tool definitions
        enable_programmatic_tools: Enable code execution tools
        container_id: Container ID for code execution
        response_format: Response format spec for JSON mode
        skip_cache: Skip response cache lookup
        user_messages_for_db: Original user messages to save to DB

    Returns:
        CompletionInternalResult with content, session_id, memory_uuids, cited_uuids
    """
    session: DBSession | None = None
    context_messages: list[Message] = []
    final_session_id = session_id or str(uuid.uuid4())

    session, context_messages, is_new_session = await get_or_create_session(
        db,
        session_id,
        project_id,
        provider,
        model,
        session_type="completion",
        external_id=external_id,
        client_id=client_id,
        request_source=request_source,
        agent_slug=agent_slug,
    )
    final_session_id = session.id

    if is_new_session:
        await publish_session_start(final_session_id, model, project_id)

    messages_dict = list(messages)
    if context_messages:
        context_as_dicts = [{"role": m.role, "content": m.content} for m in context_messages]
        messages_dict = context_as_dicts + messages_dict

    memory_facts_injected = 0
    loaded_memory_uuids: list[str] = []
    if use_memory:
        scope, scope_id = parse_memory_group_id(memory_group_id)
        try:
            messages_dict, progressive_context = await inject_progressive_context(
                messages=messages_dict,
                scope=scope,
                scope_id=scope_id,
            )
            memory_facts_injected = (
                len(progressive_context.mandates)
                + len(progressive_context.guardrails)
                + len(progressive_context.reference)
            )
            loaded_memory_uuids = progressive_context.get_loaded_uuids()
            if memory_facts_injected > 0:
                logger.info(f"complete_internal: injected {memory_facts_injected} memory facts")
                await track_loaded_batch(loaded_memory_uuids)
                await store_memory_inject_event(
                    db, final_session_id, loaded_memory_uuids, memory_facts_injected
                )
        except Exception as e:
            logger.warning(f"Memory injection failed (continuing without): {e}")

    cache = get_response_cache()
    if not skip_cache:
        cached = await cache.get(
            model=model,
            messages=messages_dict,
            temperature=temperature,
        )
        if cached:
            logger.info(f"complete_internal: returning cached response for {model}")
            if user_messages_for_db:
                await save_events(
                    db,
                    final_session_id,
                    user_messages_for_db,
                    cached.content,
                    cached.input_tokens,
                    cached.output_tokens,
                    model_used=model,
                )
            cost = estimate_cost(cached.input_tokens, cached.output_tokens, model)
            await log_token_usage(
                db,
                final_session_id,
                model,
                cached.input_tokens,
                cached.output_tokens,
                cost.total_cost_usd,
            )
            await publish_complete(
                final_session_id, cached.input_tokens, cached.output_tokens, cost.total_cost_usd
            )
            await db.commit()
            return CompletionInternalResult(
                content=cached.content,
                model=cached.model,
                provider=cached.provider,
                input_tokens=cached.input_tokens,
                output_tokens=cached.output_tokens,
                finish_reason=cached.finish_reason,
                session_id=final_session_id,
                memory_uuids=loaded_memory_uuids,
                cited_uuids=[],
                from_cache=True,
            )

    # For Claude with programmatic tools, create fresh adapter with callback for observability
    if provider == "claude" and enable_programmatic_tools:
        from app.adapters.claude import ClaudeAdapter

        async def tool_result_callback(
            tool_name: str, tool_input: dict[str, Any], tool_output: str
        ) -> None:
            await store_tool_use_event(
                db,
                final_session_id,
                tool_name=tool_name,
                tool_input=tool_input if isinstance(tool_input, dict) else {"value": tool_input},
            )
            await store_tool_result_event(
                db,
                final_session_id,
                tool_name=tool_name,
                tool_output={"content": tool_output[:2000] if tool_output else ""},
            )
            await db.commit()

        from app.adapters.gemini import GeminiAdapter
        from app.adapters.openai import OpenAIAdapter

        adapter: ClaudeAdapter | GeminiAdapter | OpenAIAdapter = ClaudeAdapter(
            after_tool_callback=tool_result_callback
        )
    else:
        adapter = get_adapter(provider)

    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages_dict]

    result = await adapter.complete(
        messages=messages_for_adapter,
        model=model,
        max_tokens=None,
        temperature=temperature,
        enable_caching=enable_caching,
        cache_ttl=cache_ttl,
        thinking_level=thinking_level,
        tools=tools,
        enable_programmatic_tools=enable_programmatic_tools,
        container_id=container_id,
        response_format=response_format,
    )

    if not skip_cache and not is_error_response(result.content):
        await cache.set(
            model=model,
            messages=messages_dict,
            temperature=temperature,
            content=result.content,
            provider=result.provider,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            finish_reason=result.finish_reason,
        )

    if user_messages_for_db:
        await save_events(
            db,
            final_session_id,
            user_messages_for_db,
            result.content,
            result.input_tokens,
            result.output_tokens,
            model_used=model,
            thinking_content=result.thinking_content,
            thinking_tokens=result.thinking_tokens,
        )
        for msg in user_messages_for_db:
            if msg.role in ("user", "system"):
                content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
                await publish_message(final_session_id, msg.role, content_str)
        await publish_message(final_session_id, "assistant", result.content, result.output_tokens)

    cost = estimate_cost(result.input_tokens, result.output_tokens, model)
    await log_token_usage(
        db, final_session_id, model, result.input_tokens, result.output_tokens, cost.total_cost_usd
    )
    await publish_complete(
        final_session_id, result.input_tokens, result.output_tokens, cost.total_cost_usd
    )

    if result.cache_metrics:
        await update_provider_metadata(
            db,
            session,
            {
                "cache_creation_input_tokens": result.cache_metrics.cache_creation_input_tokens,
                "cache_read_input_tokens": result.cache_metrics.cache_read_input_tokens,
            },
        )

    # Close one-shot sessions immediately (no continuation expected)
    # Only for new completion-type sessions without a provided session_id
    if is_new_session and session.session_type == "completion" and not session_id:
        session.status = "completed"

    await db.commit()

    cited_uuids: list[str] = []
    if loaded_memory_uuids and result.content:
        try:
            cited_prefixes = extract_uuid_prefixes(result.content)
            if cited_prefixes:
                scope, scope_id = parse_memory_group_id(memory_group_id)
                group_id = "global" if scope.value == "global" else f"{scope.value}-{scope_id}"
                prefix_to_uuid = await resolve_full_uuids(cited_prefixes, group_id)
                cited_uuids = list(prefix_to_uuid.values())
                if cited_uuids:
                    await track_referenced_batch(cited_uuids)
                    await store_memory_cite_event(db, final_session_id, cited_uuids)
                    logger.info(f"complete_internal: tracked {len(cited_uuids)} cited memory rules")
        except Exception as e:
            logger.warning(f"Citation tracking failed (continuing): {e}")

    return CompletionInternalResult(
        content=result.content,
        model=result.model,
        provider=result.provider,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        finish_reason=result.finish_reason,
        session_id=final_session_id,
        memory_uuids=loaded_memory_uuids,
        cited_uuids=cited_uuids,
        from_cache=False,
        cache_metrics=result.cache_metrics,
        thinking_content=result.thinking_content,
        thinking_tokens=result.thinking_tokens,
        tool_calls=result.tool_calls,
        container=result.container,
    )


async def stream_completion(
    messages: list[Message],
    model: str,
    provider: str,
    temperature: float,
    session_id: str,
    agent_used: str | None = None,
    model_used: str | None = None,
    fallback_used: bool = False,
    max_tokens: int | None = None,
    db: AsyncSession | None = None,
    user_messages: list[MessageInput] | None = None,
    is_new_session: bool = False,
    is_one_shot: bool = False,
) -> AsyncIterator[str]:
    """Stream completion in SSE format.

    Yields:
        SSE formatted strings: "data: {json}\n\n"
    """
    adapter = get_adapter(provider)

    input_tokens = 0
    output_tokens = 0
    accumulated_content = ""

    try:
        async for event in adapter.stream(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            if event.type == "content":
                accumulated_content += event.content or ""
                chunk = StreamingChunk(type="content", content=event.content)
                yield f"data: {chunk.model_dump_json()}\n\n"

            elif event.type == "done":
                # Capture final token counts
                if event.input_tokens is not None:
                    input_tokens = event.input_tokens
                if event.output_tokens is not None:
                    output_tokens = event.output_tokens

                # Save messages to database
                if db and user_messages and accumulated_content:
                    try:
                        await save_events(
                            db=db,
                            session_id=session_id,
                            user_messages=user_messages,
                            assistant_content=accumulated_content,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            model_used=model,
                        )
                        logger.info(f"Streaming: saved messages for session {session_id}")
                    except Exception as save_err:
                        logger.error(f"Failed to save streaming messages: {save_err}")

                # Close one-shot streaming sessions (no continuation expected)
                if db and is_new_session and is_one_shot:
                    try:
                        from sqlalchemy import select

                        result = await db.execute(
                            select(DBSession).where(DBSession.id == session_id)
                        )
                        session = result.scalar_one_or_none()
                        if session:
                            session.status = "completed"
                            await db.commit()
                            logger.info(f"Streaming: closed one-shot session {session_id}")
                    except Exception as close_err:
                        logger.error(f"Failed to close one-shot session: {close_err}")

                # Send final done event with all metadata
                done_chunk = StreamingChunk(
                    type="done",
                    model=model,
                    provider=provider,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finish_reason=event.finish_reason,
                    session_id=session_id,
                    agent_used=agent_used,
                    model_used=model_used,
                    fallback_used=fallback_used if agent_used else None,
                )
                yield f"data: {done_chunk.model_dump_json()}\n\n"

            elif event.type == "error":
                error_chunk = StreamingChunk(type="error", error=event.error)
                yield f"data: {error_chunk.model_dump_json()}\n\n"

    except Exception as e:
        logger.error(f"Streaming error: {e}")
        error_chunk = StreamingChunk(type="error", error=str(e))
        yield f"data: {error_chunk.model_dump_json()}\n\n"

    # Send [DONE] signal (OpenAI compat)
    yield "data: [DONE]\n\n"
