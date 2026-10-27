"""Step executors: one fresh native session per attempt, started from a handoff packet.

``Executor.run`` is the external effect of a step. Real executors (claude_code, codex, pi) run their
harness inside the run's git worktree and register themselves under their kind; this module ships the
registry and a scriptable faux executor so the runner is testable without any provider.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from app.llm.utils.outcomes import ProviderOutcome

from .packet import HandoffPacket

# agent_hub is Agent Hub's own tool loop (llm/tool_loop.py) on the step's agent_slug; implemented with the others in M4.
EXECUTOR_KINDS = ("claude_code", "codex", "pi", "agent_hub", "faux")

OnEvent = Callable[[Mapping[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class StepResult:
    status: Literal["completed", "failed"]
    served_models: Sequence[str] = ()
    outcome: ProviderOutcome | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    # {summary, decisions, files, open_questions}; required for a completed step.
    handoff: Mapping[str, Any] | None = None
    native_session_id: str | None = None
    transcript_path: str | None = None
    error: str | None = None
    # The attempt's last non-refused assistant output and tool actions (whole items, oldest first).
    # Never the refused turn itself. The next model in the chain gets them as partial progress.
    progress: Sequence[str] = ()


class Executor(Protocol):
    async def run(
        self, packet: HandoffPacket, model: str, worktree: Path, run_dir: Path, on_event: OnEvent
    ) -> StepResult: ...


class ExecutorUnavailable(LookupError):
    pass


_REGISTRY: dict[str, Callable[[], Executor]] = {}


def register_executor(kind: str, factory: Callable[[], Executor]) -> None:
    if kind not in EXECUTOR_KINDS:
        raise ValueError(f"unknown executor kind {kind!r}")
    _REGISTRY[kind] = factory


def get_executor(kind: str) -> Executor:
    factory = _REGISTRY.get(kind)
    if factory is None:
        raise ExecutorUnavailable(f"no executor registered for {kind!r}")
    return factory()


@dataclass(frozen=True)
class FauxAction:
    """One scripted attempt. ``kind``: success | refuse | substitute | usage_limit | crash | error."""

    kind: str = "success"
    category: str | None = None
    served_model: str | None = None
    resets_at: int | None = None
    window: str | None = None
    write: Mapping[str, str] = field(default_factory=dict)  # worktree-relative path -> content
    summary: str | None = None
    progress: Sequence[str] = ()


class FauxExecutor:
    """Scriptable executor: per step key, a list of actions consumed one per attempt (last one repeats)."""

    def __init__(self, script: Mapping[str, Sequence[FauxAction]] | None = None) -> None:
        self.script = {key: list(actions) for key, actions in (script or {}).items()}
        self.calls: list[dict[str, Any]] = []
        self._used: dict[str, int] = defaultdict(int)

    async def run(
        self, packet: HandoffPacket, model: str, worktree: Path, run_dir: Path, on_event: OnEvent
    ) -> StepResult:
        actions = self.script.get(packet.step_key) or [FauxAction()]
        action = actions[min(self._used[packet.step_key], len(actions) - 1)]
        self._used[packet.step_key] += 1
        self.calls.append(
            {
                "step": packet.step_key,
                "model": model,
                "packet": packet.render(),
                "action": action.kind,
            }
        )
        await on_event({"type": "faux_started", "model": model, "at": time.time()})
        if action.kind == "crash":
            raise RuntimeError("faux executor crashed")
        usage = {"input_tokens": 100, "output_tokens": 20}
        for relative, content in action.write.items():
            target = worktree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        progress = list(action.progress)
        if action.kind == "error":
            return StepResult("failed", [model], usage=usage, error="faux error", progress=progress)
        if action.kind == "refuse":
            outcome = ProviderOutcome(
                "refused", model, category=action.category, explanation="faux refusal"
            )
            return StepResult("failed", [model], outcome, usage, error="refused", progress=progress)
        if action.kind == "usage_limit":
            outcome = ProviderOutcome(
                "usage_limit", model, window=action.window, resets_at=action.resets_at
            )
            return StepResult(
                "failed", [model], outcome, usage, error="usage limit", progress=progress
            )
        served = action.served_model or model
        outcome = None
        if action.kind == "substitute":
            outcome = ProviderOutcome(
                "substituted", model, served_model=served, category=action.category
            )
        note = {
            "summary": action.summary or f"{packet.step_key} done on {served}",
            "decisions": [f"ran on {served}"],
            "files": sorted(action.write),
            "open_questions": [],
        }
        return StepResult(
            "completed", [served], outcome, usage, note, native_session_id=f"faux-{packet.step_key}"
        )


register_executor("faux", FauxExecutor)
