"""Subagent spawning and management.

Enables hierarchical agent patterns where a parent agent can spawn child agents
with isolated context windows to handle subtasks.

Inspired by hierarchical task-agent patterns.
"""

import asyncio
import logging
import uuid

from app.services.llm_messages import Message

from .subagent_executor import execute_subagent
from .subagent_models import SubagentConfig, SubagentResult

__all__ = ["SubagentConfig", "SubagentManager", "SubagentResult"]

logger = logging.getLogger(__name__)


class SubagentManager:
    """Manages subagent spawning and lifecycle.

    Key patterns:
    - Isolated context: Each subagent has its own message history
    - Hierarchical: Subagents can spawn child subagents
    - Traceable: OpenTelemetry correlation across subagent tree
    """

    def __init__(
        self,
        default_gemini_model: str | None = None,
        default_kimi_code_model: str | None = None,
    ):
        from app.constants import GEMINI_FLASH, KIMI_CODE_FOR_CODING

        self._default_gemini_model = default_gemini_model or GEMINI_FLASH
        self._default_kimi_code_model = default_kimi_code_model or KIMI_CODE_FOR_CODING
        self._active_subagents: dict[str, asyncio.Task[SubagentResult]] = {}

    def _get_default_model(self, provider: str) -> str:
        if provider == "kimi-code":
            return self._default_kimi_code_model
        if provider == "gemini":
            return self._default_gemini_model
        return self._default_gemini_model

    async def spawn(
        self,
        task: str,
        config: SubagentConfig,
        context: list[Message] | None = None,
        parent_id: str | None = None,
        trace_id: str | None = None,
    ) -> SubagentResult:
        """Spawn a subagent to handle a task."""
        if config.current_depth >= config.max_spawn_depth:
            raise ValueError(
                f"Spawn depth limit exceeded: current_depth={config.current_depth}, "
                f"max_spawn_depth={config.max_spawn_depth}. "
                f"Subagent '{config.name}' cannot spawn further children."
            )

        model = config.model or self._get_default_model(config.provider)

        return await execute_subagent(
            task=task,
            config=config,
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
        """Spawn a subagent in the background; returns immediately with subagent ID."""
        subagent_id = str(uuid.uuid4())[:8]

        async_task = asyncio.create_task(self.spawn(task, config, context, parent_id, trace_id))
        self._active_subagents[subagent_id] = async_task

        logger.info(f"Spawned background subagent {config.name} ({subagent_id})")
        return subagent_id

    async def get_result(
        self, subagent_id: str, timeout: float | None = None
    ) -> SubagentResult | None:
        task = self._active_subagents.get(subagent_id)
        if task is None:
            return None

        try:
            if timeout is not None:
                result = await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            else:
                result = await task
            del self._active_subagents[subagent_id]
            return result
        except TimeoutError:
            return None

    def cancel(self, subagent_id: str) -> bool:
        task = self._active_subagents.get(subagent_id)
        if task is None:
            return False

        task.cancel()
        del self._active_subagents[subagent_id]
        logger.info(f"Cancelled subagent {subagent_id}")
        return True

    @property
    def active_count(self) -> int:
        return len(self._active_subagents)
