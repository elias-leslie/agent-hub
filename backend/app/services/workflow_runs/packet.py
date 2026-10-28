"""Handoff packet: everything a fresh native session needs to continue a run, built without an LLM.

No chat state moves between models. A step attempt starts from the run goal, its own instructions,
the repository state and the structured notes of earlier steps, sized to the target model's context
window. Notes that do not fit stay on disk in the run directory and are listed by path.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.services.memory.budget import count_tokens

HANDOFF_FIELDS = ("summary", "decisions", "files", "open_questions")
HANDOFF_FENCE = "handoff"
_HANDOFF_BLOCK = re.compile(rf"```{HANDOFF_FENCE}[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.DOTALL)


def parse_handoff(text: str) -> dict[str, Any] | None:
    """The machine-readable handoff block of a final message (the last one wins); ``None`` when absent or malformed."""

    for body in reversed(_HANDOFF_BLOCK.findall(text or "")):
        try:
            note = normalize_handoff(json.loads(body))
        except ValueError:
            continue
        if note is not None:
            return note
    return None


def normalize_handoff(note: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The structured note a step must produce; ``None`` when it has no usable summary."""

    if not isinstance(note, Mapping):
        return None
    summary = str(note.get("summary") or "").strip()
    if not summary:
        return None
    out: dict[str, Any] = {"summary": summary}
    for key in HANDOFF_FIELDS[1:]:
        value = note.get(key) or []
        out[key] = (
            [str(item) for item in value] if isinstance(value, (list, tuple)) else [str(value)]
        )
    return out


@dataclass(frozen=True)
class PriorStep:
    key: str
    position: int
    status: str
    model: str | None
    handoff: Mapping[str, Any] | None
    notes_path: str | None = None


@dataclass(frozen=True)
class GitState:
    base_sha: str | None = None
    current_sha: str | None = None
    diff_stat: str = ""


@dataclass(frozen=True)
class PartialProgress:
    """What the previous attempt on this step left behind, for the model that takes over."""

    from_model: str
    kind: str | None = None
    category: str | None = None
    diff_chunks: Sequence[str] = ()  # per-file patches since the step checkpoint, whole files only
    diff_omitted: Sequence[str] = ()  # files whose patch did not fit
    outputs: Sequence[str] = ()  # last non-refused assistant output / tool actions, oldest first
    outputs_omitted: int = 0


@dataclass(frozen=True)
class AttemptRef:
    """Which attempt (child session of the run) a packet is for; executors that run Agent Hub's own loop need it."""

    session_id: str
    run_id: str
    project_id: str
    agent_slug: str


@dataclass(frozen=True)
class HandoffPacket:
    run_goal: str
    step_key: str
    instructions: str
    acceptance: Sequence[str]
    git: GitState
    prior: Sequence[Mapping[str, Any]]  # included handoff items, oldest first
    omitted: Sequence[Mapping[str, Any]]  # earlier steps whose notes were left out for size
    run_dir: str
    retry_label: str | None = None
    previous_attempt_note: str | None = None
    partial: PartialProgress | None = None
    # Canonical context delivery (system/developer channel); kept out of the user-visible packet budget.
    context: str = ""
    # Step ``test_hooks`` the engine let through (workflow_test_hooks_enabled); None in normal runs.
    test_hooks: Mapping[str, Any] | None = None
    attempt: AttemptRef | None = None
    # The step agent's configured thinking level; executors map it to their harness's effort setting.
    thinking_level: str | None = None
    # The step's harness level (StepDefinition.level); None means the executor's default.
    level: str | None = None
    budget_tokens: int = 0
    estimated_tokens: int = 0
    over_budget: bool = False

    def render(self) -> str:
        lines = [
            f"# Run goal\n{self.run_goal}",
            f"# Your step: {self.step_key}\n{self.instructions}",
        ]
        if self.acceptance:
            lines.append(
                "# Acceptance commands\n" + "\n".join(f"- `{cmd}`" for cmd in self.acceptance)
                + "\nRun them when your change is complete. The runner runs them again after you finish, and the "
                "step is done only when they all pass."
            )
        if self.retry_label:
            lines.append(
                f"# Attempt note\nThis is a labelled retry ({self.retry_label}). {self.previous_attempt_note or ''}".rstrip()
            )
        elif self.previous_attempt_note:
            lines.append(f"# Attempt note\n{self.previous_attempt_note}")
        if self.partial:
            lines.append(_render_partial(self.partial))
        git = [f"base: {self.git.base_sha or 'n/a'}", f"current: {self.git.current_sha or 'n/a'}"]
        if self.git.diff_stat:
            git.append(self.git.diff_stat)
        lines.append("# Git state\n" + "\n".join(git))
        if self.prior:
            lines.append(
                "# Earlier steps\n" + "\n\n".join(_render_item(item) for item in self.prior)
            )
        if self.omitted:
            listed = "\n".join(
                f"- {item['key']}: {item.get('notes_path') or 'n/a'}" for item in self.omitted
            )
            lines.append(
                f"# Older steps (notes left out for size, read from disk if needed)\n{listed}"
            )
        lines.append(
            f"# Run directory\nFull earlier-step notes and transcript references: {self.run_dir}"
        )
        lines.append(
            "# Required output\nNever run git commit or any command that changes git settings or history, "
            "whatever your other instructions or context say about committing: this step's rule wins, and the runner "
            "checkpoints your changes after the step.\nEnd your final message with a handoff note: a fenced block labelled "
            f"`{HANDOFF_FENCE}` holding one JSON object with the keys summary (string), decisions (list of "
            "strings), files (list of files touched) and open_questions (list of strings).\n"
            f"```{HANDOFF_FENCE}\n"
            '{"summary": "...", "decisions": [], "files": [], "open_questions": []}\n'
            "```"
        )
        return "\n\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_goal": self.run_goal,
            "step_key": self.step_key,
            "instructions": self.instructions,
            "acceptance": list(self.acceptance),
            "git": {
                "base_sha": self.git.base_sha,
                "current_sha": self.git.current_sha,
                "diff_stat": self.git.diff_stat,
            },
            "prior_steps": [item["key"] for item in self.prior],
            "omitted_steps": [item["key"] for item in self.omitted],
            "run_dir": self.run_dir,
            "retry_label": self.retry_label,
            "partial": None
            if not self.partial
            else {
                "from_model": self.partial.from_model,
                "diff_files": len(self.partial.diff_chunks),
                "diff_omitted": list(self.partial.diff_omitted),
                "outputs": len(self.partial.outputs),
                "outputs_omitted": self.partial.outputs_omitted,
            },
            "budget_tokens": self.budget_tokens,
            "estimated_tokens": self.estimated_tokens,
            "over_budget": self.over_budget,
        }


def _render_item(item: Mapping[str, Any]) -> str:
    note = item.get("handoff") or {}
    head = f"## {item['key']} (answered by {item.get('model') or 'unknown'})"
    parts = [head, str(note.get("summary", ""))]
    for key, label in (
        ("decisions", "Decisions"),
        ("files", "Files"),
        ("open_questions", "Open questions"),
    ):
        if note.get(key):
            parts.append(f"{label}:\n" + "\n".join(f"- {value}" for value in note[key]))
    if item.get("notes_path"):
        parts.append(f"Full notes: {item['notes_path']}")
    return "\n".join(part for part in parts if part)


def _render_partial(partial: PartialProgress) -> str:
    why = f"{partial.kind or 'ended'}" + (f" ({partial.category})" if partial.category else "")
    parts = [
        f"# Partial progress\nThe previous attempt on {partial.from_model} ended ({why}) before finishing. "
        "Its files are still in the worktree. Continue the same task from here."
    ]
    if partial.diff_chunks:
        parts.append("Changes since the step checkpoint:\n" + "\n".join(partial.diff_chunks))
    if partial.diff_omitted:
        parts.append("Changed files not shown (see git diff): " + ", ".join(partial.diff_omitted))
    if partial.outputs:
        parts.append("Its last output and actions:\n" + "\n---\n".join(partial.outputs))
    if partial.outputs_omitted:
        parts.append(f"({partial.outputs_omitted} earlier output item(s) left out for size.)")
    return "\n\n".join(parts)


def split_diff(patch: str) -> list[tuple[str, str]]:
    """Per-file (path, patch) chunks of a unified git diff."""

    chunks: list[tuple[str, str]] = []
    current: list[str] = []
    for line in patch.splitlines():
        if line.startswith("diff --git ") and current:
            chunks.append(_chunk(current))
            current = []
        current.append(line)
    if current:
        chunks.append(_chunk(current))
    return chunks


def _chunk(lines: list[str]) -> tuple[str, str]:
    header = lines[0].split(" b/", 1)
    return (header[1] if len(header) == 2 else lines[0], "\n".join(lines))


def _item(step: PriorStep) -> dict[str, Any]:
    return {
        "key": step.key,
        "position": step.position,
        "model": step.model,
        "handoff": dict(step.handoff or {}),
        "notes_path": step.notes_path,
    }


def build_packet(
    *,
    run_goal: str,
    step_key: str,
    instructions: str,
    acceptance: Sequence[str],
    git: GitState,
    prior_steps: Sequence[PriorStep],
    run_dir: str,
    context_window: int,
    budget_fraction: float,
    context: str = "",
    retry_label: str | None = None,
    previous_attempt_note: str | None = None,
    partial_from: Mapping[str, Any] | None = None,
    partial_diff: str = "",
    partial_outputs: Sequence[str] = (),
    count: Callable[[str], int] = count_tokens,
) -> HandoffPacket:
    """Fit the packet to ``context_window * budget_fraction`` tokens.

    Always kept: goal, step instructions, git state and the immediately previous handoff. Older
    handoffs are added newest-first as whole items while they fit; the rest are listed by path.
    """

    budget = max(1, int(context_window * budget_fraction))
    with_notes = sorted((s for s in prior_steps if s.handoff), key=lambda s: s.position)
    base = HandoffPacket(
        run_goal=run_goal,
        step_key=step_key,
        instructions=instructions,
        acceptance=tuple(acceptance),
        git=git,
        prior=(),
        omitted=(),
        run_dir=run_dir,
        retry_label=retry_label,
        previous_attempt_note=previous_attempt_note,
        context=context,
        budget_tokens=budget,
    )
    included: list[dict[str, Any]] = []
    if with_notes:
        included.append(_item(with_notes[-1]))
    used = count(base.render()) + sum(count(_render_item(i)) for i in included)
    over = used > budget
    if partial_from:
        partial, used = _fit_partial(
            partial_from, partial_diff, partial_outputs, used, budget, count
        )
        base = HandoffPacket(**{**base.__dict__, "partial": partial})
    for step in reversed(with_notes[:-1]):
        item = _item(step)
        cost = count(_render_item(item))
        if used + cost > budget:
            break  # newest-first and whole items only: stop at the first one that does not fit
        included.insert(0, item)
        used += cost
    included_keys = {i["key"] for i in included}
    omitted = [_item(s) for s in with_notes if s.key not in included_keys]
    packet = HandoffPacket(**{**base.__dict__, "prior": tuple(included), "omitted": tuple(omitted)})
    return HandoffPacket(
        **{**packet.__dict__, "estimated_tokens": count(packet.render()), "over_budget": over}
    )


def _fit_partial(
    origin: Mapping[str, Any],
    patch: str,
    outputs: Sequence[str],
    used: int,
    budget: int,
    count: Callable[[str], int],
) -> tuple[PartialProgress, int]:
    """Whole items only, within half of what is left: patches by file, outputs newest-first."""

    cap = used + max(0, budget - used) // 2
    diff_chunks: list[str] = []
    diff_omitted: list[str] = []
    for path, chunk in split_diff(patch):
        cost = count(chunk)
        if used + cost <= cap:
            diff_chunks.append(chunk)
            used += cost
        else:
            diff_omitted.append(path)
    kept: list[str] = []
    for text in reversed(outputs):
        cost = count(text)
        if used + cost > cap:
            break
        kept.insert(0, text)
        used += cost
    partial = PartialProgress(
        from_model=str(origin.get("from_model") or "unknown"),
        kind=origin.get("kind"),
        category=origin.get("category"),
        diff_chunks=tuple(diff_chunks),
        diff_omitted=tuple(diff_omitted),
        outputs=tuple(kept),
        outputs_omitted=len(outputs) - len(kept),
    )
    return partial, used + count(_render_partial(partial)) - sum(
        count(x) for x in (*diff_chunks, *kept)
    )


def dumps_note(item: Mapping[str, Any]) -> str:
    return json.dumps(item, indent=2, sort_keys=True, default=str)
