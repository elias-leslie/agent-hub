"""Persona wake workflow — event-driven agent invocations.

Dispatched by the /api/wake endpoint when external events (task failures,
quality gate failures, autocode completions) need the persona's attention.
Each wake gets its own ephemeral session for isolation.
"""

from __future__ import annotations

import logging
from typing import Any

from hatchet_sdk import Context
from pydantic import BaseModel

from app.hatchet_app import hatchet

logger = logging.getLogger(__name__)


class WakeInput(BaseModel):
    agent_slug: str
    model: str
    provider: str
    temperature: float = 0.7
    prompt: str
    project_id: str = "summitflow"
    event_type: str = "generic"
    thinking_level: str | None = None


class WakeResult(BaseModel):
    status: str
    content: str = ""
    turns: int = 0
    tool_calls: int = 0
    event_type: str = "generic"
    error: str | None = None


@hatchet.task(
    name="agent-wake",
    execution_timeout="300s",
    retries=0,
    input_validator=WakeInput,
)
async def agent_wake_task(input: WakeInput, ctx: Context) -> dict[str, Any]:
    """Run an agent completion in response to an external event."""
    from app.api.complete.core import complete_internal
    from app.db import async_session

    memory_group = f"{input.project_id}:wake:{input.event_type}"

    async with async_session() as db:
        result = await complete_internal(
            messages=[{"role": "user", "content": input.prompt}],
            model=input.model,
            provider=input.provider,
            temperature=input.temperature,
            project_id=input.project_id,
            db=db,
            agent_slug=input.agent_slug,
            use_memory=True,
            memory_group_id=memory_group,
            enable_caching=False,
            skip_cache=True,
            max_turns=10,
            execute_tools=True,
            enable_programmatic_tools=True,
            task_type="wake",
            phase=input.event_type,
            thinking_level=input.thinking_level,
        )

    out = WakeResult(
        status=result.status or "success",
        content=result.content[:500] if result.content else "",
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        event_type=input.event_type,
        error=result.error,
    )
    ctx.log(
        f"Agent wake ({input.agent_slug}/{input.event_type}): "
        f"{out.turns} turns, {out.tool_calls} tool calls"
    )
    return out.model_dump()


def dispatch_wake(
    agent_slug: str,
    model: str,
    provider: str,
    temperature: float,
    prompt: str,
    project_id: str,
    event_type: str,
    thinking_level: str | None = None,
) -> None:
    """Dispatch a wake workflow via Hatchet (fire-and-forget)."""
    wake_input = WakeInput(
        agent_slug=agent_slug,
        model=model,
        provider=provider,
        temperature=temperature,
        prompt=prompt,
        project_id=project_id,
        event_type=event_type,
        thinking_level=thinking_level,
    )
    agent_wake_task.run_no_wait(wake_input)
    logger.info("Dispatched wake workflow for %s/%s", agent_slug, event_type)
