"""Subagent spawning and management.

Enables hierarchical agent patterns where a parent agent can spawn child agents
with isolated context windows to handle subtasks.

Inspired by Claude Code's Task tool which spawns specialized agents.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from opentelemetry.trace import SpanKind, Status, StatusCode

from app.adapters.base import Message, ProviderAdapter
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.constants import OUTPUT_LIMIT_AGENTIC
from app.services.telemetry import get_current_trace_id, get_tracer

logger = logging.getLogger(__name__)


@dataclass
class SubagentConfig:
    """Configuration for a subagent."""

    name: str
    """Human-readable name for the subagent."""

    provider: Literal["claude", "gemini"] = "claude"
    """Which provider to use."""

    model: str | None = None
    """Model override. If None, uses provider default."""

    system_prompt: str | None = None
    """Custom system prompt. If None, uses default."""

    max_tokens: int = OUTPUT_LIMIT_AGENTIC
    """Maximum tokens in response."""

    temperature: float = 1.0
    """Sampling temperature."""

    thinking_level: str | None = None
    """Thinking depth: minimal/low/medium/high/ultrathink."""

    tools: list[dict[str, Any]] | None = None
    """Tool definitions available to this subagent."""

    timeout_seconds: float = 300.0
    """Maximum execution time before timeout."""


@dataclass
class SubagentResult:
    """Result from a subagent execution."""

    subagent_id: str
    """Unique ID for this subagent instance."""

    name: str
    """Name of the subagent."""

    content: str
    """Response content from the subagent."""

    status: Literal["completed", "error", "timeout", "cancelled"]
    """Execution status."""

    provider: str
    """Provider that handled the request."""

    model: str
    """Model used."""

    input_tokens: int
    """Input tokens consumed."""

    output_tokens: int
    """Output tokens generated."""

    thinking_content: str | None = None
    """Extended thinking content (if enabled)."""

    thinking_tokens: int | None = None
    """Tokens used for thinking."""

    error: str | None = None
    """Error message if status is 'error'."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When execution started."""

    completed_at: datetime | None = None
    """When execution completed."""

    parent_id: str | None = None
    """ID of parent subagent (for nested hierarchies)."""

    trace_id: str | None = None
    """OpenTelemetry trace ID for correlation."""


class SubagentManager:
    """Manages subagent spawning and lifecycle.

    Key patterns:
    - Isolated context: Each subagent has its own message history
    - Resource limits: Configurable token budgets and timeouts
    - Hierarchical: Subagents can spawn child subagents
    - Traceable: OpenTelemetry correlation across subagent tree
    """

    def __init__(
        self,
        default_claude_model: str | None = None,
        default_gemini_model: str | None = None,
    ):
        """Initialize subagent manager.

        Args:
            default_claude_model: Default model for Claude subagents.
            default_gemini_model: Default model for Gemini subagents.
        """
        from app.constants import CLAUDE_SONNET, GEMINI_FLASH

        self._default_claude_model = default_claude_model or CLAUDE_SONNET
        self._default_gemini_model = default_gemini_model or GEMINI_FLASH
        self._adapters: dict[str, ProviderAdapter] = {}
        self._active_subagents: dict[str, asyncio.Task[SubagentResult]] = {}

    def _get_adapter(self, provider: str) -> ProviderAdapter:
        """Get or create adapter for provider."""
        if provider not in self._adapters:
            if provider == "claude":
                self._adapters[provider] = ClaudeAdapter()
            elif provider == "gemini":
                self._adapters[provider] = GeminiAdapter()
            else:
                raise ValueError(f"Unknown provider: {provider}")
        return self._adapters[provider]

    def _get_default_model(self, provider: str) -> str:
        """Get default model for provider."""
        if provider == "claude":
            return self._default_claude_model
        elif provider == "gemini":
            return self._default_gemini_model
        else:
            return self._default_claude_model

    async def spawn(
        self,
        task: str,
        config: SubagentConfig,
        context: list[Message] | None = None,
        parent_id: str | None = None,
        trace_id: str | None = None,
    ) -> SubagentResult:
        """Spawn a subagent to handle a task.

        The subagent gets an isolated context window with:
        - Optional context messages (e.g., from parent)
        - The task as the user message
        - Custom system prompt if specified

        Args:
            task: The task description for the subagent.
            config: Subagent configuration.
            context: Optional context messages to include.
            parent_id: Parent subagent ID for hierarchies.
            trace_id: OpenTelemetry trace ID for correlation.

        Returns:
            SubagentResult with the response.
        """
        subagent_id = str(uuid.uuid4())[:8]
        started_at = datetime.now(UTC)

        # Get tracer and create span for this subagent execution
        tracer = get_tracer("agent-hub.orchestration.subagent")

        # Use provided trace_id or get from current context
        effective_trace_id = trace_id or get_current_trace_id()

        with tracer.start_as_current_span(
            f"subagent.spawn.{config.name}",
            kind=SpanKind.INTERNAL,
            attributes={
                "subagent.id": subagent_id,
                "subagent.name": config.name,
                "subagent.provider": config.provider,
                "subagent.model": config.model or self._get_default_model(config.provider),
                "subagent.parent_id": parent_id or "",
                "subagent.task_length": len(task),
                "subagent.timeout_seconds": config.timeout_seconds,
            },
        ) as span:
            logger.info(
                f"Spawning subagent {config.name} ({subagent_id}) "
                f"provider={config.provider} parent={parent_id} trace={effective_trace_id}"
            )

            # Build messages with isolated context
            messages: list[Message] = []

            # Add system prompt
            if config.system_prompt:
                messages.append(Message(role="system", content=config.system_prompt))

            # Add context messages if provided
            if context:
                messages.extend(context)

            # Add the task as user message
            messages.append(Message(role="user", content=task))

            # Get adapter and model
            adapter = self._get_adapter(config.provider)
            model = config.model or self._get_default_model(config.provider)

            try:
                # Execute with timeout
                result = await asyncio.wait_for(
                    adapter.complete(
                        messages=messages,
                        model=model,
                        max_tokens=config.max_tokens,
                        temperature=config.temperature,
                        thinking_level=config.thinking_level,
                        tools=config.tools,
                    ),
                    timeout=config.timeout_seconds,
                )

                # Record success in span
                span.set_attribute("subagent.status", "completed")
                span.set_attribute("subagent.input_tokens", result.input_tokens)
                span.set_attribute("subagent.output_tokens", result.output_tokens)
                span.set_attribute(
                    "subagent.total_tokens", result.input_tokens + result.output_tokens
                )
                if result.thinking_tokens:
                    span.set_attribute("subagent.thinking_tokens", result.thinking_tokens)
                span.set_status(Status(StatusCode.OK))

                # Update effective_trace_id from current span context
                span_ctx = span.get_span_context()
                if span_ctx.is_valid:
                    effective_trace_id = format(span_ctx.trace_id, "032x")

                return SubagentResult(
                    subagent_id=subagent_id,
                    name=config.name,
                    content=result.content,
                    status="completed",
                    provider=result.provider,
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    thinking_content=result.thinking_content,
                    thinking_tokens=result.thinking_tokens,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    parent_id=parent_id,
                    trace_id=effective_trace_id,
                )

            except TimeoutError:
                logger.warning(
                    f"Subagent {config.name} ({subagent_id}) timed out "
                    f"after {config.timeout_seconds}s"
                )
                span.set_attribute("subagent.status", "timeout")
                span.set_status(Status(StatusCode.ERROR, "Execution timed out"))
                span.record_exception(TimeoutError(f"Timeout after {config.timeout_seconds}s"))

                return SubagentResult(
                    subagent_id=subagent_id,
                    name=config.name,
                    content="",
                    status="timeout",
                    provider=config.provider,
                    model=model,
                    input_tokens=0,
                    output_tokens=0,
                    error=f"Execution timed out after {config.timeout_seconds} seconds",
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    parent_id=parent_id,
                    trace_id=effective_trace_id,
                )

            except Exception as e:
                logger.error(f"Subagent {config.name} ({subagent_id}) error: {e}")
                span.set_attribute("subagent.status", "error")
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)

                return SubagentResult(
                    subagent_id=subagent_id,
                    name=config.name,
                    content="",
                    status="error",
                    provider=config.provider,
                    model=model,
                    input_tokens=0,
                    output_tokens=0,
                    error=str(e),
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    parent_id=parent_id,
                    trace_id=effective_trace_id,
                )

    async def spawn_background(
        self,
        task: str,
        config: SubagentConfig,
        context: list[Message] | None = None,
        parent_id: str | None = None,
        trace_id: str | None = None,
    ) -> str:
        """Spawn a subagent in the background.

        Returns immediately with subagent ID. Use get_result() to retrieve.

        Args:
            task: The task description.
            config: Subagent configuration.
            context: Optional context messages.
            parent_id: Parent subagent ID.
            trace_id: OpenTelemetry trace ID.

        Returns:
            Subagent ID for tracking.
        """
        subagent_id = str(uuid.uuid4())[:8]

        async_task = asyncio.create_task(self.spawn(task, config, context, parent_id, trace_id))
        self._active_subagents[subagent_id] = async_task

        logger.info(f"Spawned background subagent {config.name} ({subagent_id})")
        return subagent_id

    async def get_result(
        self, subagent_id: str, timeout: float | None = None
    ) -> SubagentResult | None:
        """Get result from a background subagent.

        Args:
            subagent_id: ID returned from spawn_background.
            timeout: Maximum time to wait (None = wait forever).

        Returns:
            SubagentResult if completed, None if not found or still running.
        """
        task = self._active_subagents.get(subagent_id)
        if task is None:
            return None

        try:
            if timeout is not None:
                result = await asyncio.wait_for(task, timeout=timeout)
            else:
                result = await task
            # Clean up
            del self._active_subagents[subagent_id]
            return result
        except TimeoutError:
            return None

    def cancel(self, subagent_id: str) -> bool:
        """Cancel a background subagent.

        Args:
            subagent_id: ID of subagent to cancel.

        Returns:
            True if cancelled, False if not found.
        """
        task = self._active_subagents.get(subagent_id)
        if task is None:
            return False

        task.cancel()
        del self._active_subagents[subagent_id]
        logger.info(f"Cancelled subagent {subagent_id}")
        return True

    @property
    def active_count(self) -> int:
        """Number of active background subagents."""
        return len(self._active_subagents)
