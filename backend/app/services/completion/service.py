"""
Unified completion service for chat, voice, and streaming.

Provides a single entry point for all completion requests, handling:
- Memory injection (optional)
- Provider routing (Claude/Gemini)
- Auto-thinking detection
- Session management
- Event publishing
- Memory episode storage (for voice/chat context)
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import CompletionResult, Message
from app.api.complete.core import get_or_create_session, stream_completion
from app.api.complete.schemas import MessageInput
from app.services.agent_routing import get_provider_for_model as get_provider
from app.services.completion.auto_thinking import should_enable_thinking
from app.services.completion.episode_storage import (
    store_episode,
    store_episode_background,
)
from app.services.completion.provider_utils import get_adapter
from app.services.events import publish_session_start
from app.services.memory import inject_progressive_context, parse_memory_group_id

logger = logging.getLogger(__name__)


class CompletionSource(StrEnum):
    """Source type for completion requests."""

    CHAT = "chat"  # REST /api/complete
    VOICE = "voice"  # WebSocket /api/voice/ws
    STREAM = "stream"  # WebSocket /api/stream


@dataclass
class CompletionOptions:
    """Options for completion request."""

    model: str
    messages: list[dict[str, Any]]
    project_id: str
    max_tokens: int | None = None
    temperature: float = 1.0
    session_id: str | None = None
    external_id: str | None = None
    source: CompletionSource = CompletionSource.CHAT

    # Memory options
    use_memory: bool = False
    memory_group_id: str | None = None
    store_as_episode: bool = False  # Store conversation in memory after completion

    # Caching
    enable_caching: bool = True
    cache_ttl: str = "ephemeral"

    # Structured output
    response_format: dict[str, Any] | None = None

    # Extended thinking
    thinking_level: str | None = None  # minimal/low/medium/high/ultrathink
    auto_thinking: bool = False

    # Tools
    tools: list[dict[str, Any]] | None = None
    enable_programmatic_tools: bool = False
    container_id: str | None = None

    # Memory-triggered references
    task_type: str | None = None
    phase: str | None = None


@dataclass
class CompletionServiceResult:
    """Result from completion service."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    session_id: str
    finish_reason: str | None = None
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    tool_calls: list[Any] | None = None
    container: Any | None = None
    cache_metrics: Any | None = None
    memory_facts_injected: int = 0
    episode_uuid: str | None = None  # UUID of stored memory episode


class CompletionService:
    """
    Unified completion service for all request sources.

    Handles memory injection, provider routing, and optional episode storage.
    """

    # Track background tasks to prevent garbage collection
    _background_tasks: ClassVar[set[asyncio.Task[None]]] = set()

    def __init__(self, db: AsyncSession | None = None):
        """
        Initialize completion service.

        Args:
            db: Optional database session for session persistence.
                If None, sessions are not persisted to DB.
        """
        self.db = db

    async def complete(self, options: CompletionOptions) -> CompletionServiceResult:
        """
        Execute a completion request.

        Args:
            options: Completion options including messages, model, memory settings.

        Returns:
            CompletionServiceResult with content and metadata.
        """
        # Resolve model alias
        provider = get_provider(options.model)

        # Generate session ID if not provided
        session_id = options.session_id or str(uuid.uuid4())

        # Prepare messages
        messages_dict = list(options.messages)

        # Inject memory context if enabled
        memory_facts_injected = 0
        if options.use_memory:
            scope, scope_id = parse_memory_group_id(options.memory_group_id)
            try:
                messages_dict, context = await inject_progressive_context(
                    messages=messages_dict,
                    scope=scope,
                    scope_id=scope_id,
                    task_type=options.task_type,
                    phase=options.phase,
                )
                memory_facts_injected = len(context.mandates) + len(context.guardrails)
                if memory_facts_injected > 0:
                    logger.info(
                        f"Injected {memory_facts_injected} memories "
                        f"(source={options.source.value}, scope={scope.value})"
                    )
            except Exception as e:
                logger.warning(f"Memory injection failed (continuing without): {e}")

        # Determine thinking level
        thinking_level = options.thinking_level
        if options.auto_thinking and not thinking_level and should_enable_thinking(messages_dict):
            thinking_level = "medium"

        # Get adapter and make request
        adapter = get_adapter(provider)

        # Convert messages to adapter format
        adapter_messages = [Message(role=m["role"], content=m["content"]) for m in messages_dict]

        result: CompletionResult = await adapter.complete(
            messages=adapter_messages,
            model=options.model,
            max_tokens=options.max_tokens,
            temperature=options.temperature,
            enable_caching=options.enable_caching,
            cache_ttl=options.cache_ttl,
            thinking_level=thinking_level,
            tools=options.tools,
            enable_programmatic_tools=options.enable_programmatic_tools,
            container_id=options.container_id,
            response_format=options.response_format,
        )

        # Store conversation as memory episode if requested
        # For VOICE source, store in background (fire-and-forget) to avoid blocking response
        episode_uuid: str | None = None
        if options.store_as_episode:
            memory_group_id = options.memory_group_id or options.project_id
            if options.source == CompletionSource.VOICE:
                # Fire-and-forget for voice - don't block on slow Graphiti writes
                task = asyncio.create_task(
                    store_episode_background(
                        messages=messages_dict,
                        response=result.content,
                        source=options.source.value,
                        group_id=memory_group_id,
                    )
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            else:
                # Blocking for other sources where we want the UUID
                episode_uuid = await store_episode(
                    messages=messages_dict,
                    response=result.content,
                    source=options.source.value,
                    group_id=memory_group_id,
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
            memory_facts_injected=memory_facts_injected,
            episode_uuid=episode_uuid,
        )

    async def stream(self, options: CompletionOptions) -> AsyncIterator[str]:
        """
        Execute a streaming completion request.

        Args:
            options: Completion options including messages, model, memory settings.

        Yields:
            SSE formatted strings.
        """
        if not self.db:
            logger.warning("DB session missing for streaming request - persistence disabled")

        # Resolve model alias
        provider = get_provider(options.model)

        # Generate session ID if not provided
        session_id = options.session_id or str(uuid.uuid4())

        # Prepare messages
        messages_dict = list(options.messages)

        # Inject memory context if enabled
        memory_facts_injected = 0
        agent_used: str | None = None

        if options.model.startswith("agent:"):
            agent_used = options.model.split(":", 1)[1]

        if options.use_memory:
            scope, scope_id = parse_memory_group_id(options.memory_group_id)
            try:
                messages_dict, context = await inject_progressive_context(
                    messages=messages_dict,
                    scope=scope,
                    scope_id=scope_id,
                    task_type=options.task_type,
                    phase=options.phase,
                )
                memory_facts_injected = len(context.mandates) + len(context.guardrails)
                if memory_facts_injected > 0:
                    logger.info(
                        f"Streaming: Injected {memory_facts_injected} memories "
                        f"(scope={scope.value})"
                    )
            except Exception as e:
                logger.warning(f"Streaming: Memory injection failed (continuing without): {e}")

        # Get or create session in DB
        stream_context_messages: list[Message] = []
        is_new_session = False

        if self.db:
            session, stream_context_messages, is_new_session = await get_or_create_session(
                self.db,
                options.session_id,
                options.project_id,
                provider,
                options.model,
                session_type="chat",
                external_id=options.external_id,
                agent_slug=agent_used,
            )
            session_id = session.id
            if is_new_session:
                await publish_session_start(session_id, options.model, options.project_id)

        # Prepare messages for streaming
        new_messages = [Message(role=m["role"], content=m["content"]) for m in messages_dict]

        messages_for_streaming = (
            stream_context_messages + new_messages if stream_context_messages else new_messages
        )

        user_messages_input = [
            MessageInput(role=m["role"], content=m["content"]) for m in options.messages
        ]

        # Use async for to yield chunks from the generator
        async for chunk in stream_completion(
            messages=messages_for_streaming,
            model=options.model,
            provider=provider,
            temperature=options.temperature,
            session_id=session_id,
            agent_used=agent_used,
            model_used=options.model,
            fallback_used=False,
            max_tokens=options.max_tokens,
            db=self.db,
            user_messages=user_messages_input,
            is_new_session=is_new_session,
            is_one_shot=not options.session_id,
        ):
            yield chunk


# Convenience function for simple completions
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
    """
    Convenience function for completions with memory.

    This is the recommended way to call completions from internal code
    (voice, stream, etc.) that want memory integration.
    """
    service = CompletionService(db=db)
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
    return await service.complete(options)
