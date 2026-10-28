"""Pi step executor: one fresh unmodified ``pi --mode rpc`` session per attempt, inside the run's worktree.

Pi's model is ``provider/id``; the provider comes from the catalog provider through ``executor_defaults.json`` and
the id from the catalog's upstream id. The user's Agent Hub Pi extension is switched off for these runs
(``--no-extensions``): the step's canonical context is already in the packet and goes in through
``--append-system-prompt``, and the extension would deliver a second, differently-scoped context and ingest the
same transcript the engine ingests from ``transcript_path``. The packet's tool level (the run's, narrowed by the step)
picks the ``--tools`` flags in ``executor_defaults.json`` ``pi.levels`` (``read`` is Pi's read-only set). Pi has no
access-program support, so a catalog model that needs one fails fast and the chain moves on.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.llm.utils.outcomes import ProviderOutcome, is_model_switch

from .executor_common import (
    HarnessProcess,
    Progress,
    Usage,
    argv_tools,
    as_int,
    build_handoff,
    child_env,
    classify_failure,
    clip,
    load_defaults,
    thinking_level,
)
from .executors import OnEvent, StepResult, register_executor
from .live import PROVIDER_RETRY, THINKING, WAITING, WRITING, note_live, tool_phase
from .packet import HandoffPacket
from .usage import finish_usage, harness_basis


def message_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(
        str(block.get("text") or "")
        for block in content or []
        if isinstance(block, Mapping) and block.get("type") == "text"
    ).strip()


def pi_phase(record: Mapping[str, Any]) -> str | None:
    """What a Pi RPC record says the model is doing."""

    kind = record.get("type")
    if kind == "message_update":
        update = record.get("assistantMessageEvent")
        update = update if isinstance(update, Mapping) else {}
        shape = str(update.get("type") or "")
        if shape.startswith("thinking"):
            return THINKING
        if shape.startswith("text"):
            return WRITING
        if shape.startswith("toolcall"):
            # Pi 0.x names the tool on toolcall_start ("toolName"); the deltas after it carry no name,
            # so they keep the phase that start set. Older shapes put it in toolCall or the partial message.
            name = update.get("toolName")
            if not name:
                call = update.get("toolCall")
                if not isinstance(call, Mapping):
                    partial = update.get("partial")
                    content = partial.get("content") if isinstance(partial, Mapping) else None
                    index = update.get("contentIndex")
                    entry: Any = None
                    if isinstance(content, list) and isinstance(index, int) and 0 <= index < len(content):
                        entry = content[index]
                    call = entry if isinstance(entry, Mapping) else {}
                name = call.get("name") if isinstance(call, Mapping) else None
            return tool_phase(name) if name else None
        return None
    if kind == "tool_execution_start":
        return tool_phase(record.get("toolName"))
    if kind in ("tool_execution_end", "turn_start", "auto_retry_end"):
        return WAITING
    if kind == "auto_retry_start":
        return PROVIDER_RETRY
    return None


class PiExecutor:
    def __init__(self, defaults: Mapping[str, Any] | None = None, model_lookup: Any = None) -> None:
        self.defaults = dict(defaults or load_defaults())
        self.settings = self.defaults["pi"]
        self._model_lookup = model_lookup

    def _entry(self, model: str) -> Any:
        if self._model_lookup is not None:
            return self._model_lookup(model)
        from app.constants.catalog import get_model_entry

        return get_model_entry(model)

    def pi_model(self, model: str) -> tuple[Any, str]:
        """(catalog entry, Pi ``provider/id``); ValueError when Pi cannot run this catalog model."""

        from app.llm.model_resolver import upstream_model_id

        entry = self._entry(model)
        if entry is None:
            raise ValueError(f"{model!r} is not in the model catalog")
        if entry.access_programs:
            raise ValueError(f"{model!r} needs access programs {sorted(entry.access_programs)}, which Pi cannot send")
        provider = self.settings["provider_for_catalog_provider"].get(entry.provider)
        if provider is None:
            raise ValueError(f"no Pi provider mapped for catalog provider {entry.provider!r}")
        return entry, f"{provider}/{upstream_model_id(model, entry.provider)}"

    def command(self, packet: HandoffPacket, model: str, run_dir: Path) -> tuple[list[str], str, Path | None]:
        entry, pi_id = self.pi_model(model)
        argv = [
            self.settings["binary"],
            "--mode",
            "rpc",
            "--model",
            pi_id,
            "--thinking",
            thinking_level(packet, entry, self.defaults),
            *self.settings["flags"],
        ]
        # The run's tool level picks Pi's tool flags; a level with none leaves Pi's own default set.
        argv += self.settings["levels"][packet.level or self.settings["default_level"]]
        context_file: Path | None = None
        if packet.context:
            context_file = run_dir / "pi" / f"{packet.step_key}-{uuid.uuid4().hex[:8]}-context.md"
            argv += ["--append-system-prompt", str(context_file)]
        return argv, pi_id, context_file

    async def run(
        self, packet: HandoffPacket, model: str, worktree: Path, run_dir: Path, on_event: OnEvent
    ) -> StepResult:
        try:
            argv, pi_id, context_file = self.command(packet, model, run_dir)
        except ValueError as exc:
            return StepResult("failed", error=f"pi_unsupported: {exc}")
        if context_file is not None:
            await asyncio.to_thread(_write_context, context_file, packet.context)
        harness = await HarnessProcess.start(
            argv, worktree, child_env(self.defaults), self.defaults["stderr_tail_chars"], stdin=True
        )
        state = _Attempt(model, pi_id.split("/", 1)[1], self.defaults)
        try:
            await self._drive(harness, state, packet.render(), on_event)
        finally:
            state.returncode = await harness.stop(self.defaults["terminate_grace_seconds"])
        return replace(await self._result(state, harness, worktree), tools=argv_tools(argv))

    async def _drive(
        self, harness: HarnessProcess, state: _Attempt, prompt: str, on_event: OnEvent
    ) -> None:
        await harness.write(_command({"id": "state", "type": "get_state"}))
        await harness.write(_command({"id": "prompt", "type": "prompt", "message": prompt}))
        async for record in harness.records():
            note_live(pi_phase(record))
            await on_event({"type": "pi_event", "event": record.get("type"), "at": time.time()})
            if state.handle(record):
                break
        await harness.write(b"", close=True)  # closing stdin is Pi's orderly shutdown

    async def _result(self, state: _Attempt, harness: HarnessProcess, worktree: Path) -> StepResult:
        served = list(dict.fromkeys(state.served)) or [state.upstream]
        entry = self._entry(state.model)
        usage = finish_usage(
            state.usage.as_dict(),
            basis=harness_basis(entry.provider if entry is not None else None, self.defaults["usage"]),
            price_models=[*reversed(served), state.model],
            reported=state.cost if state.cost_reported else None,
        )
        common: dict[str, Any] = {
            "served_models": served,
            "usage": usage,
            "native_session_id": state.session_id,
            "transcript_path": state.session_file,
            "progress": tuple(state.progress.items),
        }
        failure = state.error or state.rejected
        last = state.last
        if failure is None and last is None:
            failure = harness.stderr_text or "pi ended without an assistant answer"
        if failure is None and last is not None and last.get("stopReason") in ("error", "aborted", "length"):
            failure = str(last.get("errorMessage") or f"pi stopped: {last.get('stopReason')}")
        if failure is not None:
            outcome = classify_failure(state.model, failure)
            return StepResult("failed", outcome=outcome, error=clip(failure, 1000), **common)
        outcome = None
        switched = next((m for m in reversed(state.served) if is_model_switch(state.upstream, m)), None)
        if switched:
            outcome = ProviderOutcome("substituted", state.model, served_model=switched)
        handoff = await build_handoff(state.final_text, worktree)
        return StepResult("completed", outcome=outcome, handoff=handoff, **common)


def _write_context(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _command(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload).encode() + b"\n"


class _Attempt:
    """What one Pi RPC session reported, folded record by record."""

    def __init__(self, model: str, upstream: str, defaults: Mapping[str, Any]) -> None:
        self.model, self.upstream = model, upstream
        self.session_id: str | None = None
        self.session_file: str | None = None
        self.served: list[str] = []
        self.usage = Usage()
        self.cost = 0.0  # Pi prices each assistant message from its own model table
        self.cost_reported = False
        self.progress = Progress(defaults["progress_items"])
        self.output_chars = defaults["progress_output_chars"]
        self.last: Mapping[str, Any] | None = None  # last assistant message of the run
        self.calls: dict[str, Any] = {}  # tool call id -> arguments, from the assistant messages
        self.final_text = ""
        self.rejected: str | None = None
        self.error: str | None = None
        self.returncode: int | None = None

    def handle(self, record: Mapping[str, Any]) -> bool:
        """Fold one record; True when Pi has settled and nothing more will happen."""

        kind = record.get("type")
        if kind == "response":
            self._response(record)
            return self.rejected is not None
        if kind == "message_end":
            self._message(record.get("message") or {})
        elif kind == "tool_execution_end":
            result = record.get("result") or {}
            output = clip(message_text(result), self.output_chars) if isinstance(result, Mapping) else ""
            call = self.calls.get(str(record.get("toolCallId")), {})
            arguments = record.get("args") or call
            args = json.dumps(arguments, default=str) if arguments else ""
            self.progress.add(
                f"tool {record.get('toolName')}{' ' + clip(args, 300) if args else ''}"
                f"{' (error)' if record.get('isError') else ''}" + (f"\n{output}" if output else "")
            )
        return kind == "agent_settled"

    def _response(self, record: Mapping[str, Any]) -> None:
        data: Mapping[str, Any] = record["data"] if isinstance(record.get("data"), Mapping) else {}
        if record.get("command") == "get_state" and record.get("success"):
            self.session_id, self.session_file = data.get("sessionId"), data.get("sessionFile")
        elif record.get("command") == "prompt":
            if not record.get("success"):
                self.rejected = f"pi rejected the prompt: {record.get('error')}"
            elif data.get("disposition") == "handled":
                self.rejected = "pi handled the prompt without starting a run"

    def _message(self, message: Mapping[str, Any]) -> None:
        if message.get("role") != "assistant":
            return
        usage = message.get("usage") or {}
        # Pi's input already excludes cacheRead/cacheWrite: the counters are disjoint as reported.
        self.usage.add(
            as_int(usage.get("input")),
            as_int(usage.get("cacheRead")),
            as_int(usage.get("cacheWrite")),
            as_int(usage.get("output")),
            as_int(usage.get("reasoning")),
        )
        cost = usage.get("cost")
        if isinstance(cost, Mapping) and isinstance(cost.get("total"), int | float):
            self.cost += float(cost["total"])
            self.cost_reported = True
        served = message.get("responseModel") or message.get("model")
        if served:
            self.served.append(str(served))
        self.last = message
        for block in message.get("content") or []:
            if isinstance(block, Mapping) and block.get("type") == "toolCall":
                self.calls[str(block.get("id"))] = block.get("arguments") or {}
        if message.get("stopReason") == "error":
            return  # a failed (possibly refused) turn is never partial progress
        text = message_text(message)
        if text:
            self.final_text = text
            self.progress.add(text)


register_executor("pi", PiExecutor)
