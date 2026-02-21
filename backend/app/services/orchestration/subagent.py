"""Subagent spawning and management.

Enables hierarchical agent patterns where a parent agent can spawn child agents
with isolated context windows to handle subtasks.

Inspired by Claude Code's Task tool which spawns specialized agents.
"""

import asyncio
import logging
import uuid

from app.adapters.base import Message, ProviderAdapter
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter

from .subagent_executor import execute_subagent
from .subagent_models import SubagentConfig, SubagentResult

# Re-export for backward compatibility
__all__ = ["SubagentConfig", "SubagentManager", "SubagentResult"]

logger = logging.getLogger(__name__)


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

        Raises:
            ValueError: If spawn depth limit exceeded.
        """
        if config.current_depth >= config.max_spawn_depth:
            raise ValueError(
                f"Spawn depth limit exceeded: current_depth={config.current_depth}, "
                f"max_spawn_depth={config.max_spawn_depth}. "
                f"Subagent '{config.name}' cannot spawn further children."
            )

        adapter = self._get_adapter(config.provider)
        model = config.model or self._get_default_model(config.provider)

        return await execute_subagent(
            task=task,
            config=config,
            adapter=adapter,
            model=model,
            context=context,
            parent_id=parent_id,
            trace_id=trace_id,
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
