"""Agent Hub step executor: Agent Hub's own tool loop for the step's agent, run on the attempt's worktree.

It goes through the same completion path as every Agent Hub agentic request (``complete_internal`` with
``execute_tools=True``), so routing, canonical context, tool allow-lists and typed provider outcomes behave as they do
elsewhere. The attempt's child session id is the completion ``session_id``, which keys the provider's prompt cache.
The executor is selected only by name (``executor: "agent_hub"``): no provider maps to it by default.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from app.llm.types import AssistantMessage, TextContent, ToolCall
from app.llm.utils.outcomes import ProviderOutcome, outcome_of

from .executor_common import Progress, Usage, build_handoff, clip, load_defaults
from .executors import OnEvent, StepResult, register_executor
from .hooks import refusal_hook
from .packet import HandoffPacket

Complete = Callable[..., Awaitable[Any]]
LoadAgent = Callable[[str], Awaitable[Any]]
ProvisionTools = Callable[[str, str], Awaitable[list[dict[str, Any]] | None]]


async def load_agent(slug: str) -> Any:
    from app.db import async_session
    from app.services.agent_service import get_agent_service

    async with async_session() as db:
        return await get_agent_service().get_by_slug(db, slug)


async def provision_tools(agent_slug: str, project_id: str) -> list[dict[str, Any]] | None:
    """The agent's runtime tools from the canonical allow-list, narrowed to what the project's tier shows."""

    from app.api.complete.tool_provisioner import provision_standard_tools
    from app.db import async_session
    from app.services.project_permission_service import get_visible_tools_for_project

    async with async_session() as db:
        visible = await get_visible_tools_for_project(project_id, db)
    provisioned = provision_standard_tools(
        True, None, agent_slug=agent_slug, project_id=project_id, visible_tool_names=visible
    )
    return provisioned.loaded_tools or None


def text_of(message: AssistantMessage) -> str:
    return "\n".join(b.text for b in message.content if isinstance(b, TextContent) and b.text)


class AgentHubExecutor:
    def __init__(
        self,
        defaults: Mapping[str, Any] | None = None,
        *,
        complete: Complete | None = None,
        agent_loader: LoadAgent = load_agent,
        tool_provisioner: ProvisionTools = provision_tools,
    ) -> None:
        self.defaults = dict(defaults or load_defaults())
        self._complete = complete
        self._load_agent = agent_loader
        self._provision = tool_provisioner

    async def run(
        self, packet: HandoffPacket, model: str, worktree: Path, run_dir: Path, on_event: OnEvent
    ) -> StepResult:
        attempt = packet.attempt
        if attempt is None:
            return StepResult("failed", error="agent_hub_unavailable: the packet names no attempt session")
        from app.constants.agent_limits import DEFAULT_AGENTIC_MAX_TURNS
        from app.routing.registry import get_provider_for_model
        from app.services.agent_routing_completion import thinking_level_for_provider

        agent = await self._load_agent(attempt.agent_slug)
        if agent is None:
            return StepResult("failed", error=f"agent_hub_unavailable: agent {attempt.agent_slug!r} not found")
        provider = get_provider_for_model(model)
        hook = refusal_hook(packet)
        # An injected refusal lets the loop take that many turns; the closeout turn the loop then adds is the one dropped.
        max_turns = hook.after_turn if hook is not None else DEFAULT_AGENTIC_MAX_TURNS
        complete = self._complete
        if complete is None:
            from app.api.complete.core import complete_internal as complete
            from app.constants.projects import is_cache_stale, refresh_project_cache

            if is_cache_stale():  # the tool handler only accepts working dirs under the known project roots
                await refresh_project_cache()
        tools = await self._provision(attempt.agent_slug, attempt.project_id)
        await on_event({"type": "agent_hub_started", "model": model, "at": time.time()})
        try:
            result = await asyncio.wait_for(
                complete(
                    messages=[{"role": "user", "content": packet.render()}],
                    model=model,
                    provider=provider,
                    temperature=agent.temperature,
                    project_id=attempt.project_id,
                    db=None,
                    session_id=attempt.session_id,
                    parent_session_id=attempt.run_id,
                    request_source="workflow_run",
                    agent_slug=attempt.agent_slug,
                    thinking_level=thinking_level_for_provider(provider, packet.thinking_level or agent.thinking_level),
                    max_turns=max_turns,
                    tools=tools,
                    execute_tools=True,
                    working_dir=str(worktree),
                ),
                self.defaults["max_seconds"],
            )
        except TimeoutError:
            return StepResult("failed", error=f"timeout: no completion within {self.defaults['max_seconds']}s")
        except Exception as exc:  # provider, credential and context failures end the attempt, not the engine
            return StepResult("failed", error=clip(f"agent_hub_error: {exc!r}", 1000))
        await on_event({"type": "agent_hub_finished", "at": time.time()})
        return await self._result(packet, model, worktree, result)

    async def _result(
        self, packet: HandoffPacket, model: str, worktree: Path, result: Any
    ) -> StepResult:
        message: AssistantMessage = result.message
        messages: list[AssistantMessage] = list(result.usage_messages or [message])
        outcome = next((o for m in reversed(messages) if (o := outcome_of(m)) is not None), None)
        hook = refusal_hook(packet)
        injected = False
        if hook is not None and len(messages) > hook.after_turn:
            # What a provider refusal at that turn would have recorded; the turn itself is dropped.
            outcome = ProviderOutcome(
                "refused", model, category=hook.category, explanation="injected by the workflow test hook"
            )
            messages = messages[: hook.after_turn]
            injected = True
        served = list(dict.fromkeys(m.response_model or model for m in messages))
        usage = Usage()
        for item in (m.usage for m in messages):
            usage.add(item.input, item.cache_read, item.cache_write, item.output, 0)
        used = {**usage.as_dict(), "cost_usd": sum(m.usage.cost.total for m in messages)}
        failed = injected or message.stop_reason in ("error", "aborted")
        # A refused turn never becomes progress for the next model.
        progress = Progress(self.defaults["progress_items"])
        dropped = 1 if failed and outcome is not None and not injected else 0
        for item in messages[: len(messages) - dropped]:
            for block in item.content:
                if isinstance(block, TextContent):
                    progress.add(block.text)
                elif isinstance(block, ToolCall):
                    progress.add(
                        f"{block.name}: {clip(json.dumps(block.arguments, default=str), self.defaults['progress_output_chars'])}"
                    )
        common: dict[str, Any] = {
            "served_models": served,
            "usage": used,
            "native_session_id": getattr(result, "session_id", None),
            "progress": tuple(progress.items),
        }
        if failed or (outcome is not None and outcome.kind != "substituted"):
            error = "refused" if injected else (message.error_message or result.error or "agent_hub run failed")
            return StepResult("failed", outcome=outcome, error=clip(str(error), 1000), **common)
        return StepResult(
            "completed", outcome=outcome, handoff=await build_handoff(text_of(message), worktree), **common
        )


register_executor("agent_hub", AgentHubExecutor)
