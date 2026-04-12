"""Request setup logic for completion API."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Literal, cast

from fastapi import HTTPException

from app.adapters.base import Message
from app.api.complete.core import get_or_create_session
from app.api.complete.schemas import ContextUsageInfo
from app.services.context_tracker import check_context_before_request
from app.services.event_storage import store_memory_inject_event
from app.services.events import publish_session_start
from app.services.memory import (
    inject_progressive_context,
    parse_memory_group_id,
    track_loaded_batch,
)
from app.services.memory.context_builder_settings import (
    memory_injection_enabled,
    resolve_memory_consumer_profile,
)
from app.services.response_cache import get_response_cache
from app.services.session_live_activity import mark_session_execution_start
from app.services.token_counter import count_message_tokens

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.api.complete.schemas import CompletionRequest
    from app.models import Session as DBSession
    from app.services.agent_routing import ResolvedAgent

logger = logging.getLogger(__name__)


def _memory_block_len(progressive_context: Any, field_name: str) -> int:
    """Return the size of a progressive-context block, tolerating legacy test doubles."""
    return len(getattr(progressive_context, field_name, []))


async def setup_session(
    request: CompletionRequest,
    provider: str,
    resolved_model: str,
    db: AsyncSession | None,
    client_id: str | None,
    request_source: str | None,
) -> tuple[str, DBSession | None, list[Message], bool]:
    """Get or create session.

    Args:
        request: Completion request
        provider: Provider name
        resolved_model: Resolved model
        db: Database session
        client_id: Client ID
        request_source: Request source

    Returns:
        Tuple of (session_id, session, context_messages, is_new_session)
    """
    session: DBSession | None = None
    context_messages: list[Message] = []
    session_id = request.session_id or str(uuid.uuid4())
    is_new_session = False

    if db:
        session, context_messages, is_new_session = await get_or_create_session(
            db,
            request.session_id,
            request.project_id,
            provider,
            resolved_model,
            session_type="completion",
            external_id=request.external_id,
            client_id=client_id,
            request_source=request_source,
            agent_slug=request.agent_slug,
            current_branch=request.current_branch,
            working_dir=request.working_dir,
            trace_id=request.trace_id,
            requested_provider=provider,
            requested_model=resolved_model,
        )
        session_id = session.id
        mark_session_execution_start(session)
        if is_new_session:
            await publish_session_start(session_id, resolved_model, request.project_id)

    return session_id, session, context_messages, is_new_session


def build_message_list(
    request: CompletionRequest,
    context_messages: list[Message],
) -> tuple[list[Message], list[dict[str, Any]]]:
    """Build message list from request and context.

    Args:
        request: Completion request
        context_messages: Context messages from session

    Returns:
        Tuple of (all_messages, messages_dict)
    """
    new_messages = [
        Message(role=cast(Literal["user", "assistant", "system"], m.role), content=m.content)
        for m in request.messages
    ]
    all_messages = context_messages + new_messages if context_messages else new_messages
    messages_dict = [{"role": m.role, "content": m.content} for m in all_messages]
    return all_messages, messages_dict


def _count_memory_facts(progressive_context: Any) -> int:
    """Sum facts across all memory block types."""
    return (
        _memory_block_len(progressive_context, "mandates")
        + _memory_block_len(progressive_context, "guardrails")
        + _memory_block_len(progressive_context, "reference_index")
        + _memory_block_len(progressive_context, "reference")
    )


async def _record_memory_injection(
    db: AsyncSession | None,
    session_id: str,
    loaded_memory_uuids: list[str],
    memory_facts_injected: int,
    progressive_context: Any,
    agent_slug: str | None,
) -> None:
    """Track loaded batch and optionally persist injection event."""
    await track_loaded_batch(loaded_memory_uuids)
    if not db:
        return
    memory_debug = dict(getattr(progressive_context, "debug_info", {}))
    await store_memory_inject_event(
        db, session_id, loaded_memory_uuids, memory_facts_injected,
        reference_selected_uuids=list(memory_debug.get("reference_selected_uuids", [])),
        reference_index_uuids=list(memory_debug.get("reference_index_uuids", [])),
        memory_debug=memory_debug,
        agent_id=agent_slug,
    )


async def inject_memory(
    request: CompletionRequest,
    messages_dict: list[dict[str, Any]],
    session_id: str,
    resolved_agent: ResolvedAgent | None,
    db: AsyncSession | None,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Inject memory context into messages.

    Returns:
        Tuple of (messages_dict, memory_facts_injected, loaded_memory_uuids)
    """
    agent_memory_config = resolved_agent.agent.memory_config if resolved_agent else None

    if not (request.use_memory and memory_injection_enabled(agent_memory_config)):
        return messages_dict, 0, []

    memory_facts_injected = 0
    loaded_memory_uuids: list[str] = []
    scope, scope_id = parse_memory_group_id(request.memory_group_id)
    consumer_profile = resolve_memory_consumer_profile(agent_memory_config, surface="runtime")
    try:
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
        )
        memory_facts_injected = _count_memory_facts(progressive_context)
        loaded_memory_uuids = progressive_context.get_loaded_uuids()
        if memory_facts_injected > 0:
            agent_slug = resolved_agent.agent.slug if resolved_agent else None
            await _record_memory_injection(
                db, session_id, loaded_memory_uuids, memory_facts_injected,
                progressive_context, agent_slug,
            )
    except Exception as e:
        logger.warning(f"Memory injection failed: {e}")

    return messages_dict, memory_facts_injected, loaded_memory_uuids


async def check_context_limits(
    db: AsyncSession | None,
    session: DBSession | None,
    session_id: str,
    resolved_model: str,
    messages_dict: list[dict[str, Any]],
) -> ContextUsageInfo | None:
    """Check context window usage.

    Args:
        db: Database session
        session: Session object
        session_id: Session ID
        resolved_model: Resolved model
        messages_dict: Messages as dicts

    Returns:
        ContextUsageInfo or None

    Raises:
        HTTPException: If context limit exceeded
    """
    estimated_input_tokens = count_message_tokens(messages_dict)
    context_usage_info: ContextUsageInfo | None = None

    if db and session:
        can_proceed, ctx_usage = await check_context_before_request(
            db, session_id, resolved_model, estimated_input_tokens
        )
        if not can_proceed:
            raise HTTPException(
                status_code=413,
                detail=f"Context window limit exceeded ({ctx_usage.percent_used:.0%} used).",
            )
        context_usage_info = ContextUsageInfo(
            used_tokens=ctx_usage.used_tokens,
            limit_tokens=ctx_usage.limit_tokens,
            percent_used=ctx_usage.percent_used,
            remaining_tokens=ctx_usage.remaining_tokens,
            warning=ctx_usage.warning,
        )

    return context_usage_info


async def check_cache(
    skip_cache: bool,
    resolved_model: str,
    messages_dict: list[dict[str, Any]],
    temperature: float,
) -> Any:
    """Check response cache.

    Args:
        skip_cache: Whether to skip cache
        resolved_model: Resolved model
        messages_dict: Messages as dicts
        temperature: Temperature

    Returns:
        Cached result or None
    """
    if skip_cache:
        return None

    cache = get_response_cache()
    return await cache.get(
        model=resolved_model,
        messages=messages_dict,
        temperature=temperature,
    )
