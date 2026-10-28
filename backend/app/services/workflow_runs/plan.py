"""The plan as a dependency graph: validation, readiness and the order a step's context comes in.

Pure functions over step-like objects (``step_key``, ``position``, ``status``, ``definition``), so the engine, the
revision API and the run view share one reading of the plan.

A step names the steps it depends on in ``definition["depends_on"]``. Left unset (``None``), it depends on the step
before it by position. That default looks through a step that was skipped or cancelled (it depends on what that step
depended on), so a plain chain carries on after an owner skip exactly as it always did. An explicit list does not
look through: a skipped, cancelled or failed dependency blocks the step until the plan is revised.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

# A dependency in one of these states will never complete.
DEAD = ("skipped", "cancelled", "failed", "refused")
# A dependency in one of these states may still complete.
LIVE = ("pending", "running", "needs_owner")
# Steps running at once. The scheduler takes the cap as an argument so parallel steps can raise it.
DEFAULT_MAX_RUNNING = 1


class StepLike(Protocol):
    step_key: str
    position: int
    status: str
    definition: Mapping[str, Any]


def explicit_deps(step: StepLike) -> list[str] | None:
    value = step.definition.get("depends_on")
    return list(value) if value is not None else None


def raw_deps(steps: Sequence[StepLike]) -> dict[str, list[str]]:
    """Each step's declared dependencies, the default (previous step by position) filled in. Status plays no part."""

    ordered = sorted(steps, key=lambda s: s.position)
    out: dict[str, list[str]] = {}
    for index, step in enumerate(ordered):
        declared = explicit_deps(step)
        out[step.step_key] = declared if declared is not None else ([ordered[index - 1].step_key] if index else [])
    return out


def validate_graph(nodes: Iterable[tuple[str, list[str] | None]]) -> None:
    """Raise ValueError for a duplicate key, an unknown or repeated dependency, or a cycle.

    ``nodes`` is (key, depends_on) in position order; ``None`` is the default of the previous node.
    """

    ordered = list(nodes)
    keys = [key for key, _ in ordered]
    if len(set(keys)) != len(keys):
        raise ValueError("step keys must be unique")
    known = set(keys)
    graph: dict[str, list[str]] = {}
    for index, (key, declared) in enumerate(ordered):
        deps = declared if declared is not None else ([keys[index - 1]] if index else [])
        if len(set(deps)) != len(deps):
            raise ValueError(f"step {key} lists the same dependency twice")
        unknown = [d for d in deps if d not in known]
        if unknown:
            raise ValueError(f"step {key} depends on unknown step(s): {', '.join(unknown)}")
        graph[key] = deps
    cycle = find_cycle(graph)
    if cycle:
        raise ValueError(f"dependency cycle: {' -> '.join(cycle)}")


def find_cycle(graph: Mapping[str, Sequence[str]]) -> list[str] | None:
    """One cycle as a list of keys (first repeated at the end), or None."""

    state: dict[str, int] = {}  # 1 visiting, 2 done
    path: list[str] = []

    def visit(key: str) -> list[str] | None:
        state[key] = 1
        path.append(key)
        for dep in graph.get(key, ()):
            if state.get(dep) == 1:
                return [*path[path.index(dep) :], dep]
            if dep not in state:
                found = visit(dep)
                if found:
                    return found
        path.pop()
        state[key] = 2
        return None

    for key in graph:
        if key not in state:
            found = visit(key)
            if found:
                return found
    return None


def effective_deps(steps: Sequence[StepLike]) -> dict[str, list[str]]:
    """What each step waits on now: declared dependencies, with the default looking through skipped and cancelled steps."""

    by_key = {s.step_key: s for s in steps}
    raw = raw_deps(steps)
    memo: dict[str, list[str]] = {}

    def resolve(key: str) -> list[str]:
        if key in memo:
            return memo[key]
        step = by_key[key]
        deps = raw[key]
        if explicit_deps(step) is None:
            looked: list[str] = []
            for dep in deps:
                if by_key[dep].status in ("skipped", "cancelled"):
                    looked.extend(d for d in resolve(dep) if d not in looked)
                elif dep not in looked:
                    looked.append(dep)
            deps = looked
        memo[key] = deps
        return deps

    return {key: resolve(key) for key in by_key}


@dataclass(frozen=True)
class Readiness:
    """Where a pending step stands: ready, waiting on steps that may still finish, or blocked by ones that will not."""

    state: str  # ready | waiting | blocked
    waiting_on: tuple[str, ...] = ()
    blocked_by: tuple[tuple[str, str], ...] = ()  # (dependency key, its status); "blocked" for a step that is itself blocked
    because: tuple[tuple[str, str], ...] = ()  # the dead steps (key, status) at the root of the block, however far back

    @property
    def reason(self) -> str | None:
        if self.state == "ready":
            return None
        parts = []
        if self.blocked_by:
            text = "blocked by " + ", ".join(f"{k} ({s})" for k, s in self.blocked_by)
            if any(s == "blocked" for _k, s in self.blocked_by):
                text += ", because " + ", ".join(f"{k} ({s})" for k, s in self.because)
            parts.append(text)
        if self.waiting_on:
            parts.append("waiting for " + ", ".join(self.waiting_on))
        return "; ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "waiting_on": list(self.waiting_on),
            "blocked_by": [{"key": k, "status": s} for k, s in self.blocked_by],
            "because": [{"key": k, "status": s} for k, s in self.because],
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Schedule:
    deps: dict[str, list[str]]
    readiness: dict[str, Readiness] = field(default_factory=dict)  # pending steps only
    start: list[Any] = field(default_factory=list)  # the steps to start now, by position

    @property
    def blocked(self) -> dict[str, Readiness]:
        return {k: r for k, r in self.readiness.items() if r.state == "blocked"}


def _spread_blocks(readiness: dict[str, Readiness]) -> None:
    """A pending step that waits on a blocked pending step is blocked too, with the dead steps at the root as its cause."""

    changed = True
    while changed:
        changed = False
        for key, r in list(readiness.items()):
            via = [d for d in r.waiting_on if d in readiness and readiness[d].state == "blocked"]
            if not via:
                continue
            roots = list(r.because)
            for dep in via:
                roots.extend(x for x in readiness[dep].because if x not in roots)
            readiness[key] = Readiness(
                "blocked",
                tuple(d for d in r.waiting_on if d not in via),
                (*r.blocked_by, *((d, "blocked") for d in via)),
                tuple(roots),
            )
            changed = True


def schedule(steps: Sequence[StepLike], *, max_running: int = DEFAULT_MAX_RUNNING) -> Schedule:
    """Readiness of every pending step and the ones to start: ready steps by position, as many as the cap leaves room for."""

    by_key = {s.step_key: s for s in steps}
    deps = effective_deps(steps)
    readiness: dict[str, Readiness] = {}
    for step in sorted(steps, key=lambda s: s.position):
        if step.status != "pending":
            continue
        waiting: list[str] = []
        blocked: list[tuple[str, str]] = []
        for dep in deps[step.step_key]:
            status = by_key[dep].status
            if status == "completed":
                continue
            if status in DEAD:
                blocked.append((dep, status))
            else:
                waiting.append(dep)
        if blocked:
            state = "blocked"
        elif waiting:
            state = "waiting"
        else:
            state = "ready"
        readiness[step.step_key] = Readiness(state, tuple(waiting), tuple(blocked), tuple(blocked))
    _spread_blocks(readiness)
    room = max(0, max_running - sum(1 for s in steps if s.status == "running"))
    ready = [by_key[k] for k, r in readiness.items() if r.state == "ready"]
    return Schedule(deps, readiness, ready[:room])


def context_order(steps: Sequence[StepLike], step: StepLike) -> list[str]:
    """Keys of the steps whose handoffs feed ``step``: its transitive dependencies, dependencies first.

    Ties are broken by position, so a plain chain gives the steps in position order.
    """

    deps = effective_deps(steps)
    by_key = {s.step_key: s for s in steps}
    needed: set[str] = set()
    stack = list(deps[step.step_key])
    while stack:
        key = stack.pop()
        if key not in needed:
            needed.add(key)
            stack.extend(deps[key])
    order: list[str] = []
    remaining = set(needed)
    while remaining:
        ready = sorted(
            (k for k in remaining if all(d in order or d not in needed for d in deps[k])),
            key=lambda k: by_key[k].position,
        )
        if not ready:  # cannot happen in a validated plan; never loop forever on a bad one
            ready = sorted(remaining, key=lambda k: by_key[k].position)
        order.append(ready[0])
        remaining.discard(ready[0])
    return order


def leaf_steps[T: StepLike](steps: Sequence[T], *, has_result: Callable[[T], bool] | None = None) -> list[T]:
    """The completed steps no other completed step builds on, by position: what the finished run's result is made of.

    A completed step builds on the nearest completed steps behind it, looking through steps that did not complete
    (skipped, cancelled, failed, never started): a step that was skipped or cancelled took nothing from its
    dependencies, so it must not hide them. ``has_result`` narrows which completed steps count (default: all).
    """

    usable = has_result or (lambda _s: True)
    by_key = {s.step_key: s for s in steps}
    deps = effective_deps(steps)
    completed = {s.step_key for s in steps if s.status == "completed" and usable(s)}
    built_on: set[str] = set()
    for key in completed:
        seen: set[str] = set()
        stack = list(deps[key])
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            if dep in completed:
                built_on.add(dep)  # what that step built on is already counted through it
            else:
                stack.extend(deps[dep])
    return [by_key[k] for k in sorted(completed - built_on, key=lambda k: by_key[k].position)]
