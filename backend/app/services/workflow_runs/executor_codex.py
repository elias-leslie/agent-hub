"""Codex step executor: one fresh unmodified ``codex exec --json`` per attempt, inside the run's worktree.

The model comes from the step chain (catalog id, provider prefix stripped through the catalog's upstream id), the
cyber access program from the catalog entry (standard when the model needs none), reasoning effort from the
agent's thinking level. Sandbox and approvals are data (``executor_defaults.json``): workspace-write, never ask.
The packet's canonical context goes in as developer instructions next to the user's own Codex ones.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import time
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.llm.utils.outcomes import ProviderOutcome, is_model_switch
from app.llm.utils.refusal_codes import reroute_category

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


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def user_developer_instructions() -> str:
    """The developer instructions from the user's Codex config; a ``-c`` override would otherwise replace them."""

    with contextlib.suppress(OSError, ValueError):
        config = tomllib.loads((codex_home() / "config.toml").read_text())
        return str(config.get("developer_instructions") or "")
    return ""


def rollout_path(thread_id: str, home: Path | None = None) -> Path | None:
    matches = sorted((home or codex_home()).glob(f"sessions/*/*/*/rollout-*-{thread_id}.jsonl"))
    return matches[-1] if matches else None


def read_rollout(path: Path | None) -> tuple[list[str], str | None, dict[str, Any] | None]:
    """(models in turn order, last error code, reroute) recorded in the rollout transcript."""

    models: list[str] = []
    info: str | None = None
    reroute: dict[str, Any] | None = None
    if path is None:
        return models, info, reroute
    with contextlib.suppress(OSError):
        for line in path.read_text(errors="replace").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            payload = record.get("payload") if isinstance(record, Mapping) else None
            if not isinstance(payload, Mapping):
                continue
            kind = str(payload.get("type") or record.get("type") or "")
            if record.get("type") == "turn_context" and payload.get("model"):
                models.append(str(payload["model"]))
            if "reroute" in kind.lower().replace("_", ""):
                reroute = dict(payload)
            error = payload.get("error")
            if isinstance(error, Mapping) and error.get("codex_error_info"):
                info = str(error["codex_error_info"])
    return models, info, reroute


def reroute_outcome(requested: str, event: Mapping[str, Any]) -> ProviderOutcome:
    reason = event.get("reason")
    return ProviderOutcome(
        "substituted",
        requested,
        served_model=event.get("toModel") or event.get("to_model"),
        category=reroute_category(reason),
        explanation=str(reason) if reason else None,
    )


class CodexExecutor:
    def __init__(self, defaults: Mapping[str, Any] | None = None, model_lookup: Any = None) -> None:
        self.defaults = dict(defaults or load_defaults())
        self.settings = self.defaults["codex"]
        self._model_lookup = model_lookup

    def _entry(self, model: str) -> Any:
        if self._model_lookup is not None:
            return self._model_lookup(model)
        from app.constants.catalog import get_model_entry

        return get_model_entry(model)

    def command(self, packet: HandoffPacket, model: str, worktree: Path) -> tuple[list[str], str, str]:
        """(argv, upstream model, access program) for one attempt; the prompt goes in on stdin."""

        from app.llm.model_resolver import upstream_model_id

        entry = self._entry(model)
        provider = entry.provider if entry is not None else self.settings["catalog_provider"]
        if provider != self.settings["catalog_provider"]:
            raise ValueError(f"{model!r} is a {provider!r} model, not a Codex model")
        upstream = upstream_model_id(model, self.settings["catalog_provider"])
        program = ((entry.access_programs or {}).get("cyber") if entry is not None else None) or self.settings[
            "default_cyber_program"
        ]
        effort = thinking_level(packet, entry, self.defaults)
        instructions = "\n\n".join(v for v in (user_developer_instructions(), packet.context) if v)
        argv = [
            self.settings["binary"],
            "exec",
            "--json",
            "--model",
            upstream,
            "--cyber-access-program",
            program,
            "--sandbox",
            self.settings["sandbox"],
            "-c",
            f"approval_policy={json.dumps(self.settings['approval_policy'])}",
            "-c",
            f"model_reasoning_effort={json.dumps(effort)}",
        ]
        if packet.context:
            argv += ["-c", "developer_instructions=" + json.dumps(instructions)]
        argv += ["-C", str(worktree), "-"]
        return argv, upstream, program

    async def run(
        self, packet: HandoffPacket, model: str, worktree: Path, run_dir: Path, on_event: OnEvent
    ) -> StepResult:
        try:
            argv, upstream, _ = self.command(packet, model, worktree)
        except ValueError as exc:
            return StepResult("failed", error=f"codex_unsupported: {exc}")
        binary = shutil.which(argv[0])
        if binary is None:
            return StepResult("failed", error=f"codex_unavailable: {argv[0]!r} is not installed")
        argv[0] = binary
        harness = await HarnessProcess.start(
            argv,
            worktree,
            child_env(self.defaults),
            self.defaults["stderr_tail_chars"],
            stdin=True,
        )
        state = _Attempt(model, upstream, self.defaults)
        try:
            await harness.write(packet.render().encode(), close=True)
            await asyncio.wait_for(self._consume(harness, state, on_event), self.defaults["max_seconds"])
        except TimeoutError:
            state.error = f"timeout: no completion within {self.defaults['max_seconds']}s"
        finally:
            state.returncode = await harness.stop(self.defaults["terminate_grace_seconds"])
        return await self._result(state, harness, worktree)

    async def _consume(self, harness: HarnessProcess, state: _Attempt, on_event: OnEvent) -> None:
        async for event in harness.records():
            await on_event({"type": "codex_event", "event": event.get("type"), "at": time.time()})
            state.handle(event)

    async def _result(self, state: _Attempt, harness: HarnessProcess, worktree: Path) -> StepResult:
        models, rollout_info, reroute = read_rollout(
            rollout_path(state.thread_id) if state.thread_id else None
        )
        transcript = rollout_path(state.thread_id) if state.thread_id else None
        served = [m for m in dict.fromkeys(models) if m] or [state.upstream]
        common: dict[str, Any] = {
            "served_models": served,
            "usage": state.usage.as_dict(),
            "native_session_id": state.thread_id,
            "transcript_path": str(transcript) if transcript else None,
            "progress": tuple(state.progress.items),
        }
        failure = state.failure or (
            None if state.completed else (state.error or harness.stderr_text or "codex ended without completing the turn")
        )
        if failure is not None:
            outcome = classify_failure(state.model, failure, state.error_info or rollout_info)
            return StepResult(
                "failed", outcome=outcome, error=clip(failure, 1000), **common
            )
        outcome = None
        switched = next((m for m in reversed(served) if is_model_switch(state.upstream, m)), None)
        event = state.reroute or reroute
        if event is not None or switched:
            outcome = reroute_outcome(state.model, event or {})
            if switched and not outcome.served_model:
                outcome = ProviderOutcome(
                    "substituted", state.model, served_model=switched, category=outcome.category
                )
        handoff = await build_handoff(state.final_text, worktree)
        return StepResult("completed", outcome=outcome, handoff=handoff, **common)


class _Attempt:
    """What one ``codex exec --json`` run reported, folded event by event."""

    def __init__(self, model: str, upstream: str, defaults: Mapping[str, Any]) -> None:
        self.model, self.upstream = model, upstream
        self.thread_id: str | None = None
        self.final_text = ""
        self.usage = Usage()
        self.progress = Progress(defaults["progress_items"])
        self.output_chars = defaults["progress_output_chars"]
        self.completed = False
        self.failure: str | None = None
        self.error: str | None = None
        self.error_info: Any = None
        self.reroute: Mapping[str, Any] | None = None
        self.returncode: int | None = None
        self._error_texts: list[str] = []

    def handle(self, event: Mapping[str, Any]) -> None:
        kind = str(event.get("type") or "")
        if kind == "thread.started":
            self.thread_id = event.get("thread_id")
        elif kind == "item.completed":
            self._item(event.get("item") or {})
        elif kind == "turn.completed":
            usage = event.get("usage") or {}
            cached = as_int(usage.get("cached_input_tokens"))
            written = as_int(usage.get("cache_write_input_tokens"))
            # input_tokens counts cached input; keep the four counters disjoint.
            self.usage.add(
                as_int(usage.get("input_tokens")) - cached - written,
                cached,
                written,
                as_int(usage.get("output_tokens")),
                as_int(usage.get("reasoning_output_tokens")),
            )
            self.completed = True
        elif kind in ("turn.failed", "error"):
            error: Mapping[str, Any] = event["error"] if isinstance(event.get("error"), Mapping) else event
            message = str(error.get("message") or event.get("message") or kind)
            info = error.get("codex_error_info") or error.get("codexErrorInfo") or event.get("codex_error_info")
            if kind == "turn.failed":
                self.failure = message
                self.error_info = info or self.error_info
            else:  # a stream error: becomes the failure unless the turn still completes
                self._error_texts.append(message)
                self.error_info = info or self.error_info
                self.error = message
        elif "reroute" in kind.lower().replace("_", "").replace("/", ""):
            self.reroute = event.get("params") if isinstance(event.get("params"), Mapping) else event

    def _item(self, item: Mapping[str, Any]) -> None:
        kind = item.get("type")
        if kind == "agent_message":
            self.final_text = str(item.get("text") or "")
            self.progress.add(self.final_text)
        elif kind == "command_execution":
            output = clip(str(item.get("aggregated_output") or "").strip(), self.output_chars)
            self.progress.add(
                f"$ {item.get('command')} (exit {item.get('exit_code')})" + (f"\n{output}" if output else "")
            )
        elif kind == "file_change":
            changes = item.get("changes") or []
            listed = ", ".join(f"{c.get('kind')} {c.get('path')}" for c in changes if isinstance(c, Mapping))
            self.progress.add(f"file change: {listed}" if listed else "file change")
        elif kind in ("mcp_tool_call", "web_search", "collab_tool_call"):
            self.progress.add(f"{kind}: {clip(json.dumps(item, default=str), self.output_chars)}")
        elif kind == "error":
            self._error_texts.append(str(item.get("message") or ""))


register_executor("codex", CodexExecutor)
