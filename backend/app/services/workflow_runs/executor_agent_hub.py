"""Agent Hub step executor: Agent Hub's own tool loop for the step's agent, run on the attempt's worktree.

It goes through the same completion path as every Agent Hub agentic request (``complete_internal`` with
``execute_tools=True``), so routing, canonical context, tool allow-lists and typed provider outcomes behave as they do
elsewhere. The attempt's child session id is the completion ``session_id``, which keys the provider's prompt cache.
The executor is selected only by name (``executor: "agent_hub"``): no provider maps to it by default.

The step ``level`` (``executor_defaults.json`` ``agent_hub.levels``) sets how much the loop carries. ``lean`` (the default)
mirrors Pi's lean start: a short working-rules prompt with the worktree as cwd, and only the core tools. The agent's
canonical context still comes first in the system prompt, and tool permission and safety checks are unchanged. ``full``
is the agent's whole provisioned tool set and no extra prompt.

The tool set comes from the packet's tool level, which the run sets (``read``, ``lean`` or ``full``; a step may only
narrow it): the agent's tools narrowed to the level's list. The attempt's tool names are the permission, both for which
tools the model is shown and for which calls run. The
tools the attempt got are recorded on the result. A step that needs a shell and a write tool (acceptance commands, or a
level that lists them) and does not have them ends at once with ``tools_unavailable`` and no model call; the engine
treats it like an unavailable model (next chain entry, else the owner).

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

from app.llm.types import AssistantMessage, TextContent, ToolCall
from app.llm.utils.outcomes import ProviderOutcome, outcome_of

from .agent_hub_transcript import Transcript, persist_transcript
from .executor_common import Progress, Usage, build_handoff, clip, load_defaults
from .executors import OnEvent, StepResult, register_executor
from .hooks import refusal_hook
from .live import PROVIDER_RETRY, THINKING, WAITING, WRITING, note_live, tool_phase
from .packet import HandoffPacket
from .usage import agent_hub_basis, finish_usage

Complete = Callable[..., Awaitable[Any]]
LoadAgent = Callable[[str], Awaitable[Any]]
ProvisionTools = Callable[[str, str], Awaitable[list[dict[str, Any]] | None]]
RecordTranscript = Callable[[Transcript], Awaitable[None]]

logger = logging.getLogger(__name__)


def loop_phase(event: Any) -> str | None:
    """What a tool-loop event says the model or its tools are doing (None: activity that changes nothing)."""

    kind = str(getattr(event, "type", "") or "")
    if kind.startswith("thinking"):
        return THINKING
    if kind.startswith("text"):
        return WRITING
    if kind in ("toolcall_start", "toolcall_delta", "toolcall_end"):
        call = getattr(event, "tool_call", None)
        if call is None:
            content = getattr(getattr(event, "partial", None), "content", None) or []
            index = getattr(event, "content_index", None)
            call = content[index] if isinstance(index, int) and 0 <= index < len(content) else None
        return tool_phase(getattr(call, "name", None))
    if kind == "tool_run_start":
        return tool_phase(getattr(event.tool_call, "name", None))
    if kind in ("start", "tool_run_complete", "tool_run_error", "done"):
        return WAITING
    if kind == "turn_retry":
        return PROVIDER_RETRY
    return None


class LoopLog:
    """Collects what the tool loop reports while it runs: finished turns, tool results by call id and retries.

    A crash ends the loop without a result, so this is what the transcript keeps of the partial run.
    """

    def __init__(self) -> None:
        self.tool_results: dict[str, Any] = {}
        self.retries: list[tuple[int, str]] = []
        self.messages: list[AssistantMessage] = []
        self.budget_exhausted: int | None = None  # the finite turn budget the loop ran into, if it did

    @property
    def turns(self) -> int:
        return len(self.messages)

    def __call__(self, event: Any) -> None:
        kind = getattr(event, "type", None)
        note_live(loop_phase(event))
        if kind in ("tool_run_complete", "tool_run_error"):
            self.tool_results[event.tool_call.id] = event.result
        elif kind == "turn_retry":
            self.retries.append((self.turns, event.reason))
        elif kind == "turn_budget_exhausted":
            self.budget_exhausted = event.max_turns
        elif kind in ("done", "error"):
            message = getattr(event, "message", None) if kind == "done" else getattr(event, "error", None)
            if message is not None:
                self.messages.append(message)


async def load_agent(slug: str) -> Any:
    from app.db import async_session
    from app.services.agent_service import get_agent_service

    async with async_session() as db:
        return await get_agent_service().get_by_slug(db, slug)


async def provision_tools(agent_slug: str, project_id: str) -> list[dict[str, Any]] | None:
    """The agent's runtime tools from the canonical allow-list."""

    from app.api.complete.tool_provisioner import provision_standard_tools

    provisioned = provision_standard_tools(True, None, agent_slug=agent_slug)
    return provisioned.loaded_tools or None


def missing_tools(
    names: list[str], acceptance: tuple[str, ...] | list[str], level: Mapping[str, Any], settings: Mapping[str, Any]
) -> list[str]:
    """What a step needs but its tool set lacks: a shell tool and a write tool (empty when it needs neither).

    A step needs them when it has acceptance commands or its level's own tool list carries a shell or write tool.
    Which tools count as shell and write is data (``executor_defaults.json`` ``agent_hub``).
    """

    shell, write = set(settings["shell_tools"]), set(settings["write_tools"])
    if not acceptance and not (set(level.get("tools") or ()) & (shell | write)):
        return []
    have = set(names)
    return [
        *([" or ".join(sorted(shell))] if not shell & have else []),
        *([" or ".join(sorted(write))] if not write & have else []),
    ]


def lean_surface(
    level: Mapping[str, Any], tools: list[dict[str, Any]] | None, worktree: Path
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """(tools, system prompt) for a level: the agent's tools narrowed to the level's list, plus its working-rules prompt.

    A level with no tool list keeps everything. If the agent's allow-list shares none of the level's tools, the level
    keeps the agent's list only when its data says so (``agent_tools_if_none_match``, so an agent with its own tool
    domain still starts with tools); otherwise the step has none. A level never adds a tool the agent does not have.
    """

    allowed = level.get("tools")
    template = level.get("prompt")
    if not allowed:
        return tools, None
    kept = [tool for tool in tools or [] if tool.get("name") in allowed]
    if not kept:
        return (tools, None) if level.get("agent_tools_if_none_match") else ([], None)
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

    @staticmethod
    def _partial(transcript: Transcript, loop_log: LoopLog, error: str) -> Transcript:
        """What the model did before the run died: the turns and tool results collected so far, then the error."""

        return replace(
            transcript,
            turns=list(loop_log.messages),
            tool_results=loop_log.tool_results,
            retries=tuple(loop_log.retries),
            error=error,
        )

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
        from app.routing.registry import get_provider_for_model
        from app.services.agent_routing_completion import thinking_level_for_provider

        agent = await self._load_agent(attempt.agent_slug)
        if agent is None:
            return StepResult("failed", error=f"agent_hub_unavailable: agent {attempt.agent_slug!r} not found")
        provider = get_provider_for_model(model)
        hook = refusal_hook(packet)
        # No turn budget: the attempt ends on the model's own stop, a provider outcome, an error or a cancel. Only an
        # injected refusal (a test hook) bounds it: the loop takes that many turns, and the closeout turn it then adds
        # is the one dropped.
        max_turns = hook.after_turn if hook is not None else None
        complete = self._complete
        if complete is None:
            from app.api.complete.core import complete_internal as complete
            from app.constants.projects import is_cache_stale, refresh_project_cache

            if is_cache_stale():  # the tool handler only accepts working dirs under the known project roots
                await refresh_project_cache()
        settings = self.defaults["agent_hub"]
        level_name = packet.level or settings["default_level"]
        level = settings["levels"].get(level_name)
        if level is None:
            return StepResult("failed", error=f"agent_hub_unsupported: unknown level {packet.level!r}")
        tools, prompt = lean_surface(level, await self._provision(attempt.agent_slug, attempt.project_id), worktree)
        names = [str(tool.get("name")) for tool in tools or []]
        if lacking := missing_tools(names, packet.acceptance, level, settings):
            # The run's tool level left the step without what it needs: no model call, the next chain entry or the owner decides.
            return StepResult(
                "failed",
                error=f"tools_unavailable: tool level {level_name!r} allows only [{', '.join(names)}]; this step needs {' and '.join(lacking)}",
                tools=names,
            )
        messages: list[dict[str, Any]] = [{"role": "user", "content": packet.render()}]
        if prompt:  # the agent's own prompt layer: the canonical context goes ahead of it
            messages.insert(0, {"role": "system", "content": prompt})
        await on_event({"type": "agent_hub_started", "model": model, "at": time.time()})
        loop_log = LoopLog()
        transcript = Transcript(attempt.session_id, attempt.agent_slug, model, input_messages=tuple(messages))
        abort = asyncio.Event()  # set when this coroutine is cancelled: the provider request in flight stops with it
        try:
            result = await complete(
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
                permitted_tools=frozenset(names),
                execute_tools=True,
                working_dir=str(worktree),
                on_loop_event=loop_log,
                signal=abort,
            )
        except asyncio.CancelledError:
            # A cancel (owner, worker stop) ends the provider request too, and what the attempt did is still saved.
            abort.set()
            await self._record(self._partial(transcript, loop_log, "cancelled"))
            raise
        except Exception as exc:  # provider, credential and context failures end the attempt, not the engine
            error = clip(f"agent_hub_error: {exc!r}", 1000)
            await self._record(self._partial(transcript, loop_log, error))
            return StepResult("failed", error=error, tools=names)
        await on_event({"type": "agent_hub_finished", "at": time.time()})
        turns = list(result.usage_messages or [result.message])
        await self._record(
            replace(transcript, turns=turns, tool_results=loop_log.tool_results, retries=tuple(loop_log.retries))
        )
        if loop_log.budget_exhausted is not None and hook is None:
            # Never a quiet success: the model was cut off while it still wanted tools, and its closeout answer is
            # not the finished work.
            return StepResult(
                "failed",
                error=f"turn_budget_exhausted: the tool loop stopped after {loop_log.budget_exhausted} turns while the "
                "model still wanted tools",
                tools=names,
            )
        return await self._result(packet, model, worktree, result, names)

    async def _result(
        self, packet: HandoffPacket, model: str, worktree: Path, result: Any, tools: list[str]
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
        # Imported here: app.api's package init imports the workflow routes, which import the engine and these executors.
        from app.api.complete.runtime_usage import served_model

        served = list(dict.fromkeys(served_model(m, model) for m in messages))
        usage = Usage()
        for item in (m.usage for m in messages):
            usage.add(item.input, item.cache_read, item.cache_write, item.output, item.reasoning)
        counts = usage.as_dict()
        # The per-turn cost is the adapter's own catalog pricing, the same figure the attempt's cost rows carry.
        used = finish_usage(
            counts,
            basis=agent_hub_basis(model, counts),
            price_models=[*reversed(served), model],
            reported=sum(m.usage.cost.total for m in messages),
            reported_source="catalog_estimate",
        )
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
            "tools": tools,
        }
        if failed or (outcome is not None and outcome.kind != "substituted"):
            error = "refused" if injected else (message.error_message or result.error or "agent_hub run failed")
            return StepResult("failed", outcome=outcome, error=clip(str(error), 1000), **common)
        return StepResult(
            "completed", outcome=outcome, handoff=await build_handoff(text_of(message), worktree), **common
        )


register_executor("agent_hub", AgentHubExecutor)
