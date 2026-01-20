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
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import CompletionResult, Message
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.constants import DEFAULT_OUTPUT_LIMIT
from app.services.memory import inject_memory_context, parse_memory_group_id
from app.services.memory.service import MemorySource, get_memory_service

logger = logging.getLogger(__name__)


class CompletionSource(str, Enum):
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
    max_tokens: int = DEFAULT_OUTPUT_LIMIT
    temperature: float = 1.0
    session_id: str | None = None
    purpose: str | None = None
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


# Thinking trigger keywords
_THINKING_TRIGGERS = [
    "ultrathink",
    "think hard",
    "think carefully",
    "think step by step",
    "analyze",
    "evaluate",
    "compare",
    "explain why",
    "reason",
    "think through",
    "consider carefully",
    "debug",
    "review code",
    "find the bug",
    "what's wrong",
    "refactor",
    "multi-step",
    "complex",
    "edge cases",
]

# Adapter cache
_adapter_cache: dict[str, ClaudeAdapter | GeminiAdapter] = {}


def _get_provider(model: str) -> str:
    """Determine provider from model name."""
    model_lower = model.lower()
    if "claude" in model_lower:
        return "claude"
    elif "gemini" in model_lower:
        return "gemini"
    return "claude"


def _get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter:
    """Get cached adapter instance."""
    if provider in _adapter_cache:
        return _adapter_cache[provider]

    adapter: ClaudeAdapter | GeminiAdapter
    if provider == "claude":
        adapter = ClaudeAdapter()
    elif provider == "gemini":
        adapter = GeminiAdapter()
    else:
        raise ValueError(f"Unknown provider: {provider}")

    _adapter_cache[provider] = adapter
    return adapter


def _extract_text_content(content: str | list[dict[str, Any]]) -> str:
    """Extract text from message content."""
    if isinstance(content, str):
        return content
    texts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block.get("text", ""))
        elif isinstance(block, str):
            texts.append(block)
    return " ".join(texts)


def _should_enable_thinking(messages: list[dict[str, Any]]) -> bool:
    """Detect if request would benefit from extended thinking."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            text_content = _extract_text_content(msg.get("content", ""))
            content_lower = text_content.lower()
            for trigger in _THINKING_TRIGGERS:
                if trigger in content_lower:
                    return True
            if any(f"{i}." in text_content for i in range(1, 10)):
                return True
            break
    return False


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
        from app.api.openai_compat import MODEL_MAPPING

        resolved_model = MODEL_MAPPING.get(options.model, options.model)
        provider = _get_provider(resolved_model)

        # Generate session ID if not provided
        session_id = options.session_id or str(uuid.uuid4())

        # Prepare messages
        messages_dict = list(options.messages)

        # Inject memory context if enabled
        memory_facts_injected = 0
        if options.use_memory:
            scope, scope_id = parse_memory_group_id(options.memory_group_id)
            try:
                messages_dict, memory_facts_injected = await inject_memory_context(
                    messages=messages_dict,
                    scope=scope,
                    scope_id=scope_id,
                    max_facts=10,
                )
                if memory_facts_injected > 0:
                    logger.info(
                        f"Injected {memory_facts_injected} memory facts "
                        f"(source={options.source.value}, scope={scope.value})"
                    )
            except Exception as e:
                logger.warning(f"Memory injection failed (continuing without): {e}")

        # Determine thinking level
        thinking_level = options.thinking_level
        if options.auto_thinking and not thinking_level and _should_enable_thinking(messages_dict):
            thinking_level = "medium"

        # Get adapter and make request
        adapter = _get_adapter(provider)

        # Convert messages to adapter format
        adapter_messages = [Message(role=m["role"], content=m["content"]) for m in messages_dict]

        result: CompletionResult = await adapter.complete(
            messages=adapter_messages,
            model=resolved_model,
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
            store_args = {
                "messages": messages_dict,
                "response": result.content,
                "source": options.source,
                "group_id": options.memory_group_id or options.project_id,
            }
            if options.source == CompletionSource.VOICE:
                # Fire-and-forget for voice - don't block on slow Graphiti writes
                task = asyncio.create_task(self._store_episode_background(**store_args))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            else:
                # Blocking for other sources where we want the UUID
                episode_uuid = await self._store_episode(**store_args)

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

    async def _store_episode(
        self,
        messages: list[dict[str, Any]],
        response: str,
        source: CompletionSource,
        group_id: str,
    ) -> str | None:
        """
        Store conversation as a memory episode.

        Args:
            messages: The conversation messages.
            response: The assistant's response.
            source: Source of the conversation (chat, voice, stream).
            group_id: Memory group ID for isolation.

        Returns:
            UUID of the created episode, or None if storage failed.
        """
        try:
            # Get the last user message for episode content
            last_user_msg = next(
                (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            user_text = _extract_text_content(last_user_msg)

            # Build episode content (user input + assistant response)
            episode_content = f"User: {user_text}\nAssistant: {response}"

            # Map source to memory source
            memory_source = (
                MemorySource.VOICE if source == CompletionSource.VOICE else MemorySource.CHAT
            )

            # Store episode
            memory_service = get_memory_service(group_id)
            episode_uuid = await memory_service.add_episode(
                content=episode_content,
                source=memory_source,
                source_description=f"{source.value} conversation",
                reference_time=datetime.now(UTC),
            )

            logger.info(f"Stored {source.value} conversation as episode {episode_uuid}")
            return episode_uuid

        except Exception as e:
            logger.warning(f"Failed to store episode: {e}")
            return None

    async def _store_episode_background(
        self,
        messages: list[dict[str, Any]],
        response: str,
        source: CompletionSource,
        group_id: str,
    ) -> None:
        """
        Background wrapper for episode storage with error handling.

        Used for fire-and-forget storage (e.g., voice) where we don't want to
        block the response. Errors are logged but don't propagate.
        """
        try:
            await self._store_episode(
                messages=messages,
                response=response,
                source=source,
                group_id=group_id,
            )
        except Exception as e:
            # Log but don't raise - this is fire-and-forget
            logger.error(f"Background episode storage failed: {e}")


# Convenience function for simple completions
async def complete_with_memory(
    messages: list[dict[str, Any]],
    model: str,
    project_id: str,
    source: CompletionSource = CompletionSource.CHAT,
    use_memory: bool = True,
    store_as_episode: bool = True,
    memory_group_id: str | None = None,
    max_tokens: int = DEFAULT_OUTPUT_LIMIT,
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
