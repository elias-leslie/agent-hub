"""
Unified completion service for chat, voice, and streaming.
"""

import asyncio
import logging
import uuid
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import CompletionResult, Message
from app.services.agent_routing import get_provider_for_model as get_provider
from app.services.completion.helpers import (
    get_thinking_level,
    handle_episode_storage,
    inject_memory_context,
)
from app.services.completion.provider_utils import get_adapter
from app.services.completion.types import (
    CompletionOptions,
    CompletionServiceResult,
    CompletionSource,
)

logger = logging.getLogger(__name__)


class CompletionService:
    """Unified completion service for all request sources."""

    _background_tasks: ClassVar[set[asyncio.Task[None]]] = set()

    def __init__(self, db: AsyncSession | None = None):
        self.db = db

    async def complete(self, options: CompletionOptions) -> CompletionServiceResult:
        """Execute a completion request."""
        provider = get_provider(options.model)
        session_id = options.session_id or str(uuid.uuid4())
        messages, memory_facts = await inject_memory_context(options, list(options.messages))

        adapter = get_adapter(provider)
        result: CompletionResult = await adapter.complete(
            messages=[Message(role=m["role"], content=m["content"]) for m in messages],
            model=options.model,
            max_tokens=options.max_tokens,
            temperature=options.temperature,
            enable_caching=options.enable_caching,
            cache_ttl=options.cache_ttl,
            thinking_level=get_thinking_level(options, messages),
            tools=options.tools,
            enable_programmatic_tools=options.enable_programmatic_tools,
            container_id=options.container_id,
            response_format=options.response_format,
        )

        episode_uuid = await handle_episode_storage(
            options, messages, result.content, self._background_tasks
        )

        return CompletionServiceResult(
            content=result.content,
            model=result.model,
            provider=result.provider,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            session_id=session_id,
            finish_reason=result.finish_reason,
            thinking_content=result.thinking_content,
            thinking_tokens=result.thinking_tokens,
            tool_calls=result.tool_calls,
            container=result.container,
            cache_metrics=result.cache_metrics,
            memory_facts_injected=memory_facts,
            episode_uuid=episode_uuid,
        )


async def complete_with_memory(
    messages: list[dict[str, Any]],
    model: str,
    project_id: str,
    source: CompletionSource = CompletionSource.CHAT,
    use_memory: bool = True,
    store_as_episode: bool = True,
    memory_group_id: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 1.0,
    db: AsyncSession | None = None,
) -> CompletionServiceResult:
    """Convenience function for completions with memory."""
    options = CompletionOptions(
        model=model,
        messages=messages,
        project_id=project_id,
        source=source,
        use_memory=use_memory,
        store_as_episode=store_as_episode,
        memory_group_id=memory_group_id,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return await CompletionService(db=db).complete(options)
