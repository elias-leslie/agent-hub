"""Agent Hub step executor: Agent Hub's own tool loop for the step's agent, run on the attempt's worktree.

It goes through the same completion path as every Agent Hub agentic request (``complete_internal`` with
``execute_tools=True``), so routing, canonical context, tool allow-lists and typed provider outcomes behave as they do
elsewhere. The attempt's child session id is the completion ``session_id``, which keys the provider's prompt cache.
The executor is selected only by name (``executor: "agent_hub"``): no provider maps to it by default.

The step ``level`` (``executor_defaults.json`` ``agent_hub.levels``) sets how much the loop carries. ``lean`` (the default)
mirrors Pi's lean start: a short working-rules prompt with the worktree as cwd, and only the core tools. The agent's
canonical context still comes first in the system prompt, and tool permission and safety checks are unchanged. ``full``
is the agent's whole provisioned tool set and no extra prompt.

The loop runs with no database open. Afterwards the executor writes the attempt's transcript onto its child session
(``agent_hub_transcript``): the session's events, with the served model and token usage (reasoning tokens when the
provider reports them) per turn, plus cost rows. The run view's per-attempt ``session_id`` is the way to read it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.api.complete.runtime_usage import served_model
from app.llm.types import AssistantMessage, TextContent, ToolCall
from app.llm.utils.outcomes import ProviderOutcome, outcome_of

from .agent_hub_transcript import Transcript, persist_transcript
from .executor_common import Progress, Usage, build_handoff, clip, load_defaults
from .executors import OnEvent, StepResult, register_executor
from .hooks import refusal_hook
from .packet import HandoffPacket

Complete = Callable[..., Awaitable[Any]]
LoadAgent = Callable[[str], Awaitable[Any]]
ProvisionTools = Callable[[str, str], Awaitable[list[dict[str, Any]] | None]]
RecordTranscript = Callable[[Transcript], Awaitable[None]]

logger = logging.getLogger(__name__)


class LoopLog:
    """Collects what the tool loop reports while it runs: tool results by call id and interrupted-turn retries."""

    def __init__(self) -> None:
        self.tool_results: dict[str, Any] = {}
        self.retries: list[tuple[int, str]] = []
        self.turns = 0

    def __call__(self, event: Any) -> None:
        kind = getattr(event, "type", None)
        if kind in ("tool_run_complete", "tool_run_error"):
            self.tool_results[event.tool_call.id] = event.result
        elif kind == "turn_retry":
            self.retries.append((self.turns, event.reason))
        elif kind in ("done", "error"):
            self.turns += 1


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


def lean_surface(
    level: Mapping[str, Any], tools: list[dict[str, Any]] | None, worktree: Path
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """(tools, system prompt) for a level: the agent's tools narrowed to the level's list, plus its working-rules prompt.

    A level with no tool list keeps everything. If the agent's allow-list shares none of the level's tools the full
    list stays, so a step never starts without tools; the level never adds a tool the agent does not already have.
    """

    allowed = level.get("tools")
    template = level.get("prompt")
    if not allowed:
        return tools, None
    kept = [tool for tool in tools or [] if tool.get("name") in allowed]
    if not kept:
        return tools, None
    listing = "\n".join(f"- {tool['name']}: {allowed[tool['name']]}" for tool in kept)
    prompt = "\n".join(template).replace("{tools}", listing).replace("{cwd}", str(worktree)) if template else None
    return kept, prompt


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
        transcript_writer: RecordTranscript = persist_transcript,
    ) -> None:
        self.defaults = dict(defaults or load_defaults())
        self._complete = complete
        self._load_agent = agent_loader
        self._provision = tool_provisioner
        self._write_transcript = transcript_writer

    async def _record(self, transcript: Transcript) -> None:
        """The transcript is evidence, not the step's outcome: a failed write is logged and the step carries on."""

        try:
            await self._write_transcript(transcript)
        except Exception:
            logger.exception("agent_hub step transcript for %s was not saved", transcript.session_id)

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
        settings = self.defaults["agent_hub"]
        level = settings["levels"].get(packet.level or settings["default_level"])
        if level is None:
            return StepResult("failed", error=f"agent_hub_unsupported: unknown level {packet.level!r}")
        tools, prompt = lean_surface(level, await self._provision(attempt.agent_slug, attempt.project_id), worktree)
        messages: list[dict[str, Any]] = [{"role": "user", "content": packet.render()}]
        if prompt:  # the agent's own prompt layer: the canonical context goes ahead of it
            messages.insert(0, {"role": "system", "content": prompt})
        await on_event({"type": "agent_hub_started", "model": model, "at": time.time()})
        loop_log = LoopLog()
        transcript = Transcript(attempt.session_id, attempt.agent_slug, model, input_messages=tuple(messages))
        try:
            result = await asyncio.wait_for(
                complete(
                    messages=messages,
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
                    on_loop_event=loop_log,
                ),
                self.defaults["max_seconds"],
            )
        except TimeoutError:
            error = f"timeout: no completion within {self.defaults['max_seconds']}s"
            await self._record(replace(transcript, error=error))
            return StepResult("failed", error=error)
        except Exception as exc:  # provider, credential and context failures end the attempt, not the engine
            error = clip(f"agent_hub_error: {exc!r}", 1000)
            await self._record(replace(transcript, error=error))
            return StepResult("failed", error=error)
        await on_event({"type": "agent_hub_finished", "at": time.time()})
        turns = list(result.usage_messages or [result.message])
        await self._record(
            replace(transcript, turns=turns, tool_results=loop_log.tool_results, retries=tuple(loop_log.retries))
        )
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
        # The catalog identity of what answered each turn; a provider-reported different model is kept as reported.
        served = list(dict.fromkeys(served_model(m, model) for m in messages))
        usage = Usage()
        for item in (m.usage for m in messages):
            usage.add(item.input, item.cache_read, item.cache_write, item.output, item.reasoning)
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
