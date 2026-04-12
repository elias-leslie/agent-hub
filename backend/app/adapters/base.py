"""Base protocol and types for provider adapters."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

# Re-export core types
from .errors import (
    AuthenticationError,
    CircuitBreakerError,
    ProviderError,
    RateLimitError,
    is_retriable_error,
    with_retry,
)
from .runtime_session import ProviderRuntimeSession, StreamBackedRuntimeSession
from .types import (
    CacheMetrics,
    CompletionResult,
    ContainerState,
    Message,
    StreamEvent,
    ToolCallResult,
)
from .utils import ToolCallIdNormalizer

__all__ = [
    "AuthenticationError",
    "CacheMetrics",
    "CircuitBreakerError",
    "CompletionResult",
    "ContainerState",
    "Message",
    "ProviderAdapter",
    "ProviderError",
    "ProviderRuntimeSession",
    "RateLimitError",
    "StreamBackedRuntimeSession",
    "StreamEvent",
    "ToolCallIdNormalizer",
    "ToolCallResult",
    "is_retriable_error",
    "with_retry",
]


class ProviderAdapter(ABC):
    """Protocol for AI provider adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'claude', 'gemini')."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Generate a completion for the given messages.

        Args:
            messages: Conversation history
            model: Model identifier to use
            max_tokens: Maximum tokens in response (optional - models use defaults if None)
            temperature: Sampling temperature
            cache_retention: Prompt caching hint — "none" (default), "short", or "long".
                Activates per-block ``cache_control`` on system prompts for
                Anthropic direct API.  Other providers accept the parameter but
                treat it as a no-op.
            **kwargs: Provider-specific parameters.
                abort_event (asyncio.Event): Set to signal graceful cancellation.
                    Adapters that support it will check ``abort_event.is_set()``
                    during streaming and raise ``asyncio.CancelledError``.

        Returns:
            CompletionResult with generated content and metadata

        Raises:
            ProviderError: If the request fails
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is available and working."""
        ...

    async def start_tool_session(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None,
        max_turns: int,
        project_id: str | None,
        session_id: str,
        agent_slug: str | None,
        tool_catalog: list[dict[str, Any]] | None,
    ) -> ProviderRuntimeSession:
        """Start a provider-owned tool runtime session.

        Tool-capable adapters may override this to expose richer session
        ownership. The default path wraps the legacy canonical tool-event
        stream so callers can treat all providers as session-shaped.
        """
        complete_with_tool_events = getattr(self, "complete_with_tool_events", None)
        if complete_with_tool_events is None:
            raise NotImplementedError(
                f"{type(self).__name__} does not support tool runtime sessions",
            )
        return StreamBackedRuntimeSession(
            complete_with_tool_events(
                messages=messages,
                model=model,
                tools=tools,
                working_dir=working_dir,
                max_turns=max_turns,
                project_id=project_id,
                session_id=session_id,
                agent_slug=agent_slug,
                tool_catalog=tool_catalog,
            ),
        )

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """
        Stream a completion for the given messages.

        Args:
            messages: Conversation history
            model: Model identifier to use
            max_tokens: Maximum tokens in response (optional - models use defaults if None)
            temperature: Sampling temperature
            cache_retention: Prompt caching hint — "none" (default), "short", or "long".
                Currently only actionable for Anthropic direct API adapters; other
                providers accept the parameter but treat it as a no-op.
            **kwargs: Provider-specific parameters

        Yields:
            StreamEvent with content chunks and metadata

        Raises:
            ProviderError: If the request fails
        """
        # Default implementation: call complete and yield single event
        result = await self.complete(messages, model, max_tokens, temperature, cache_retention=cache_retention, **kwargs)
        yield StreamEvent(type="content", content=result.content)
        yield StreamEvent(
            type="done",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            finish_reason=result.finish_reason,
        )
