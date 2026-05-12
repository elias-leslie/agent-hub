"""Helper functions for completion service."""

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import Message
from app.api.complete.session_repo import get_or_create_session
from app.services.completion.auto_thinking import should_enable_thinking
from app.services.completion.episode_storage import (
    store_episode,
    store_episode_background,
)
from app.services.completion.types import CompletionOptions, CompletionSource
from app.services.events import publish_session_start
from app.services.memory import inject_progressive_context, parse_memory_group_id
from app.services.memory.context_builder_settings import resolve_memory_consumer_profile

logger = logging.getLogger(__name__)


def _memory_block_len(progressive_context: object, field_name: str) -> int:
    """Return the size of a progressive-context block, tolerating legacy test doubles."""
    return len(getattr(progressive_context, field_name, []))


async def inject_memory_context(
    options: CompletionOptions, messages: list[dict[str, Any]], is_stream: bool = False
) -> tuple[list[dict[str, Any]], int]:
    """Inject memory context if enabled."""
    if not options.use_memory:
        return messages, 0

    scope, scope_id = parse_memory_group_id(options.memory_group_id)
    try:
        consumer_profile = resolve_memory_consumer_profile(options.memory_config, surface="runtime")
        messages, context = await inject_progressive_context(
            messages=messages,
            scope=scope,
            scope_id=scope_id,
            variant=options.memory_variant_override,
            task_type=options.task_type,
            phase=options.phase,
            session_id=options.session_id,
            project_id=options.project_id,
            external_id=options.external_id,
            memory_config=options.memory_config,
            current_branch=options.current_branch,
            consumer_profile=consumer_profile,
        )
        count = (
            _memory_block_len(context, "mandates")
            + _memory_block_len(context, "guardrails")
            + _memory_block_len(context, "reference_index")
            + _memory_block_len(context, "reference")
        )
        if count > 0:
            prefix = "Streaming: " if is_stream else ""
            logger.info(f"{prefix}Injected {count} memories (scope={scope.value})")
        return messages, count
    except Exception as e:
        prefix = "Streaming: " if is_stream else ""
        logger.warning(f"{prefix}Memory injection failed (continuing without): {e}")
        return messages, 0


def get_thinking_level(options: CompletionOptions, messages: list[dict[str, Any]]) -> str | None:
    """Determine thinking level based on options and content."""
    thinking_level = options.thinking_level
    if options.auto_thinking and not thinking_level and should_enable_thinking(messages):
        thinking_level = "medium"
    return thinking_level


async def handle_episode_storage(
    options: CompletionOptions,
    messages: list[dict[str, Any]],
    response: str,
    background_tasks: set[asyncio.Task[None]],
) -> str | None:
    """Store conversation as memory episode if requested."""
    if not options.store_as_episode:
        return None

    memory_group_id = options.memory_group_id or options.project_id
    if options.source == CompletionSource.VOICE:
        task = asyncio.create_task(
            store_episode_background(
                messages=messages,
                response=response,
                source=options.source.value,
                group_id=memory_group_id,
            )
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        return None

    return await store_episode(
        messages=messages,
        response=response,
        source=options.source.value,
        group_id=memory_group_id,
    )


async def get_stream_session(
    db: AsyncSession,
    options: CompletionOptions,
    provider: str,
    agent_used: str | None,
) -> tuple[str, list[Message], bool]:
    """Get or create session for streaming."""
    session, stream_context_messages, is_new_session = await get_or_create_session(
        db,
        options.session_id,
        options.project_id,
        provider,
        options.model,
        session_type="chat",
        external_id=options.external_id,
        agent_slug=agent_used,
    )
    if is_new_session:
        await publish_session_start(session.id, options.model, options.project_id)
    return session.id, stream_context_messages, is_new_session
