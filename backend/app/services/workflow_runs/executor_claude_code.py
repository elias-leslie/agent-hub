"""Claude Code step executor: one fresh unmodified headless ``claude`` per attempt, inside the run's worktree.

The CLI runs with its own tools under the permission mode in ``executor_defaults.json`` and the packet's canonical
context as appended system prompt. Refusal, substitution and usage-limit detection is the provider's own
(``llm/provider_support/claude_stream.py``); ``switchModelsOnFlag`` is off and ``child_env`` disables the CLI's refusal
fallback, so a flagged turn fails instead of being answered by another model. The CLI keeps its own login: this module
never reads or forwards credentials. The native JSONL transcript stays where Claude Code wrote it, for session ingestion.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.llm.provider_support.claude_code_cli import child_env, claude_binary
from app.llm.provider_support.claude_stream import SYNTHETIC_MODEL, ClaudeTurnObserver, result_error

from .executor_common import (
    HarnessProcess,
    Progress,
    Usage,
    as_int,
    build_handoff,
    clip,
    load_defaults,
    thinking_level,
)
from .executors import OnEvent, StepResult, register_executor
from .hooks import refusal_hook
from .packet import HandoffPacket


def claude_home() -> Path:
    return Path.home() / ".claude"


def transcript_path(session_id: str | None, worktree: Path, home: Path | None = None) -> Path | None:
    """The native JSONL Claude Code wrote for ``session_id`` (under its per-directory project folder)."""

    if not session_id:
        return None
    projects = (home or claude_home()) / "projects"
    expected = projects / re.sub(r"[^A-Za-z0-9]", "-", str(worktree.resolve())) / f"{session_id}.jsonl"
    if expected.is_file():
        return expected
    found = sorted(projects.glob(f"*/{session_id}.jsonl"))
    return found[-1] if found else None


def refusal_event(category: str, explanation: str) -> dict[str, Any]:
    """The synthetic assistant record Claude Code writes for a safeguard refusal (same shape, same detection)."""

    return {
        "type": "assistant",
        "message": {
            "model": SYNTHETIC_MODEL,
            "role": "assistant",
            "stop_reason": "refusal",
            "stop_details": {"type": "refusal", "category": category, "explanation": explanation},
            "content": [{"type": "text", "text": f"Details: `[{category}]`"}],
        },
    }


class ClaudeCodeExecutor:
    def __init__(self, defaults: Mapping[str, Any] | None = None) -> None:
        self.defaults = dict(defaults or load_defaults())
        self.settings = self.defaults["claude_code"]

    def command(self, packet: HandoffPacket, model: str, binary: str) -> tuple[list[str], str]:
        """(argv, upstream model) for one attempt; the prompt goes in on stdin as a stream-json user turn."""

        from app.constants.catalog import get_model_entry
        from app.llm.model_resolver import upstream_model_id

        upstream = upstream_model_id(model, self.settings["catalog_provider"])
        argv = [
            binary,
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            upstream,
            "--effort",
            thinking_level(packet, get_model_entry(model), self.defaults),
            "--permission-mode",
            self.settings["permission_mode"],
            "--setting-sources",
            self.settings["setting_sources"],
            "--settings",
            json.dumps(self.settings["settings"]),
            *self.settings["levels"][packet.level or self.settings["default_level"]],
        ]
        if packet.context:
            argv += ["--append-system-prompt", packet.context]
        return argv, upstream

    async def run(
        self, packet: HandoffPacket, model: str, worktree: Path, run_dir: Path, on_event: OnEvent
    ) -> StepResult:
        binary = claude_binary()
        if binary is None:
            return StepResult("failed", error="claude_unavailable: Claude Code CLI is not installed")
        try:
            argv, upstream = self.command(packet, model, binary)
        except ValueError as exc:
            return StepResult("failed", error=f"claude_unsupported: {exc}")
        harness = await HarnessProcess.start(
            argv, worktree, child_env(), self.defaults["stderr_tail_chars"], stdin=True
        )
        state = _Attempt(model, upstream, self.defaults, refusal_hook(packet))
        try:
            turn = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": packet.render()}]}}
            await harness.write(json.dumps(turn).encode() + b"\n", close=True)
            await asyncio.wait_for(self._consume(harness, state, on_event), self.defaults["max_seconds"])
        except TimeoutError:
            state.error = f"timeout: no completion within {self.defaults['max_seconds']}s"
        finally:
            state.returncode = await harness.stop(self.defaults["terminate_grace_seconds"])
        return await self._result(state, harness, worktree)

    async def _consume(self, harness: HarnessProcess, state: _Attempt, on_event: OnEvent) -> None:
        async for event in harness.records():
            await on_event({"type": "claude_code_event", "event": event.get("type"), "at": time.time()})
            state.handle(event)
            if state.injected or event.get("type") == "result":
                return

    async def _result(self, state: _Attempt, harness: HarnessProcess, worktree: Path) -> StepResult:
        observer = state.observer
        served = list(dict.fromkeys([*state.served, *sorted(observer.served)]))
        path = transcript_path(state.session_id, worktree)
        common: dict[str, Any] = {
            "served_models": served or [state.upstream],
            "usage": state.usage_dict(),
            "native_session_id": state.session_id,
            "transcript_path": str(path) if path else None,
            "progress": tuple(state.progress.items),
        }
        typed = observer.outcome(state.upstream)
        outcome = typed[0] if typed else None
        succeeded = observer.succeeded() and not state.injected
        if typed is not None and (typed[0].kind != "substituted" or not succeeded):
            return StepResult("failed", outcome=typed[0], error=clip(typed[1], 1000), **common)
        if not succeeded:
            error = state.error or result_error(
                observer.result, harness.process.returncode, harness.stderr_text
            )
            return StepResult("failed", error=clip(error or "claude ended without completing the turn", 1000), **common)
        final = str((observer.result or {}).get("result") or "") or (
            observer.answer_text[-1] if observer.answer_text else ""
        )
        return StepResult(
            "completed", outcome=outcome, handoff=await build_handoff(final, worktree), **common
        )


class _Attempt:
    """What one ``claude -p`` run reported, folded event by event."""

    def __init__(self, model: str, upstream: str, defaults: Mapping[str, Any], hook: Any) -> None:
        self.model, self.upstream = model, upstream
        self.observer = ClaudeTurnObserver()
        self.progress = Progress(defaults["progress_items"])
        self.output_chars = defaults["progress_output_chars"]
        self.hook = hook
        self.served: list[str] = []
        self.session_id: str | None = None
        self.turns: set[str] = set()
        self.message_usage: dict[str, Mapping[str, Any]] = {}
        self.injected = False
        self.error: str | None = None
        self.returncode: int | None = None
        # Subscription window use (fraction of the limit) as of the last rate_limit_event the CLI emitted.
        self.windows: dict[str, float] = {}

    def handle(self, event: dict[str, Any]) -> None:
        self.session_id = str(event.get("session_id") or self.session_id or "") or None
        if event.get("type") == "rate_limit_event":
            self._rate_limit(event.get("rate_limit_info"))
        self.observer.handle(event)
        if event.get("type") == "assistant":
            self._assistant(event.get("message") or {})
            if self.hook is not None and self.hook.due(len(self.turns)) and not self.injected:
                self.injected = True
                self.observer.handle(
                    refusal_event(self.hook.category, "injected by the workflow test hook (no provider contacted)")
                )

    def _rate_limit(self, info: Any) -> None:
        windows = info.get("unifiedWindows") if isinstance(info, Mapping) else None
        for name, window in (windows or {}).items():
            if isinstance(window, Mapping) and isinstance(window.get("utilization"), int | float):
                self.windows[str(name)] = float(window["utilization"])

    def _assistant(self, message: Mapping[str, Any]) -> None:
        name = message.get("model")
        if not name or name == SYNTHETIC_MODEL:
            return  # a refused turn never becomes progress
        if name not in self.served:
            self.served.append(str(name))
        key = str(message.get("id") or len(self.turns))
        self.turns.add(key)
        if isinstance(message.get("usage"), Mapping):
            self.message_usage[key] = message["usage"]
        for block in message.get("content") or []:
            if block.get("type") == "text":
                self.progress.add(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                self.progress.add(f"{block.get('name')}: {clip(json.dumps(block.get('input'), default=str), self.output_chars)}")

    def usage_dict(self) -> dict[str, Any]:
        result = self.observer.result or {}
        raw = [result["usage"]] if isinstance(result.get("usage"), Mapping) else list(self.message_usage.values())
        usage = Usage()
        for item in raw:
            details = item.get("output_tokens_details") or {}
            usage.add(
                as_int(item.get("input_tokens")),
                as_int(item.get("cache_read_input_tokens")),
                as_int(item.get("cache_creation_input_tokens")),
                as_int(item.get("output_tokens")),
                as_int(details.get("thinking_tokens")) if isinstance(details, Mapping) else 0,
            )
        out: dict[str, Any] = {**usage.as_dict()}
        for key in ("total_cost_usd", "duration_ms", "num_turns"):
            if result.get(key) is not None:
                out[key] = result[key]
        if isinstance(result.get("modelUsage"), Mapping):
            out["by_model"] = result["modelUsage"]
        if self.windows:
            out["rate_limit_windows"] = dict(self.windows)
        return out


register_executor("claude_code", ClaudeCodeExecutor)
