"""Pi step executor: one fresh unmodified ``pi --mode rpc`` session per attempt, inside the run's worktree.

Pi's model is ``provider/id``; the provider comes from the catalog provider through ``executor_defaults.json`` and
the id from the catalog's upstream id. The user's Agent Hub Pi extension is switched off for these runs
(``--no-extensions``): the step's canonical context is already in the packet and goes in through
``--append-system-prompt``, and the extension would deliver a second, differently-scoped context and ingest the
same transcript the engine ingests from ``transcript_path``. Pi has no access-program support, so a catalog model
that needs one fails fast and the chain moves on.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.llm.utils.outcomes import ProviderOutcome, is_model_switch

from .executor_common import (
    HarnessProcess,
    Progress,
    Usage,
    as_int,
    build_handoff,
    child_env,
    classify_failure,
    clip,
    load_defaults,
    thinking_level,
)
from .executors import OnEvent, StepResult, register_executor
from .packet import HandoffPacket


def message_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(
        str(block.get("text") or "")
        for block in content or []
        if isinstance(block, Mapping) and block.get("type") == "text"
    ).strip()


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
        if self.settings.get("tools"):
            argv += ["--tools", ",".join(self.settings["tools"])]
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
            context_file.parent.mkdir(parents=True, exist_ok=True)
            context_file.write_text(packet.context)
        harness = await HarnessProcess.start(
            argv, worktree, child_env(self.defaults), self.defaults["stderr_tail_chars"], stdin=True
        )
        state = _Attempt(model, pi_id.split("/", 1)[1], self.defaults)
        try:
            await asyncio.wait_for(
                self._drive(harness, state, packet.render(), on_event), self.defaults["max_seconds"]
            )
        except TimeoutError:
            state.error = f"timeout: no completion within {self.defaults['max_seconds']}s"
        finally:
            state.returncode = await harness.stop(self.defaults["terminate_grace_seconds"])
        return await self._result(state, harness, worktree)

    async def _drive(
        self, harness: HarnessProcess, state: _Attempt, prompt: str, on_event: OnEvent
    ) -> None:
        await harness.write(_command({"id": "state", "type": "get_state"}))
        await harness.write(_command({"id": "prompt", "type": "prompt", "message": prompt}))
        async for record in harness.records():
            await on_event({"type": "pi_event", "event": record.get("type"), "at": time.time()})
            if state.handle(record):
                break
        await harness.write(b"", close=True)  # closing stdin is Pi's orderly shutdown

    async def _result(self, state: _Attempt, harness: HarnessProcess, worktree: Path) -> StepResult:
        served = list(dict.fromkeys(state.served)) or [state.upstream]
        common: dict[str, Any] = {
            "served_models": served,
            "usage": state.usage.as_dict(),
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
