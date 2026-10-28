"""The plan graph: validation, readiness and context order, without a database."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.services.workflow_runs.plan import context_order, effective_deps, schedule, validate_graph


@dataclass
class S:
    step_key: str
    position: int
    status: str = "pending"
    definition: dict[str, Any] = field(default_factory=dict)


def plan(*specs: tuple[str, str, list[str] | None]) -> list[S]:
    return [S(k, i, status, {"depends_on": deps}) for i, (k, status, deps) in enumerate(specs)]


def test_validate_graph_rejects_unknown_repeated_and_circular_dependencies() -> None:
    validate_graph([("a", None), ("b", ["a"]), ("c", ["a", "b"])])
    with pytest.raises(ValueError, match="unknown"):
        validate_graph([("a", ["x"])])
    with pytest.raises(ValueError, match="twice"):
        validate_graph([("a", None), ("b", ["a", "a"])])
    with pytest.raises(ValueError, match="cycle: a -> b -> a"):
        validate_graph([("a", ["b"]), ("b", ["a"])])
    with pytest.raises(ValueError, match="unique"):
        validate_graph([("a", None), ("a", None)])


def test_ready_steps_are_the_pending_ones_whose_dependencies_completed_first_by_position() -> None:
    steps = plan(("a", "completed", []), ("b", "pending", ["a"]), ("c", "pending", ["a"]), ("d", "pending", ["b", "c"]))
    result = schedule(steps)
    assert [s.step_key for s in result.start] == ["b"]  # one running at a time
    assert [s.step_key for s in schedule(steps, max_running=2).start] == ["b", "c"]  # a cap that can be raised
    assert result.readiness["d"].state == "waiting" and result.readiness["d"].waiting_on == ("b", "c")
    steps[1].status = "running"
    assert schedule(steps).start == [] and [s.step_key for s in schedule(steps, max_running=2).start] == ["c"]


def test_a_dead_explicit_dependency_blocks_but_the_default_chain_looks_through() -> None:
    explicit = plan(("a", "skipped", []), ("b", "pending", ["a"]))
    blocked = schedule(explicit)
    assert blocked.start == [] and blocked.readiness["b"].reason == "blocked by a (skipped)"
    chain = plan(("a", "completed", None), ("b", "cancelled", None), ("c", "pending", None))
    assert effective_deps(chain)["c"] == ["a"] and [s.step_key for s in schedule(chain).start] == ["c"]


def test_context_is_the_transitive_dependencies_in_topological_order() -> None:
    steps = plan(
        ("d", "pending", ["b", "c"]), ("b", "completed", ["a"]), ("c", "completed", ["a"]),
        ("a", "completed", []), ("other", "completed", []),
    )
    assert context_order(steps, steps[0]) == ["a", "b", "c"]
    assert context_order(steps, steps[3]) == []


def test_a_cap_counts_the_steps_already_running_and_only_ready_steps_start() -> None:
    steps = plan(
        ("a", "running", []), ("b", "pending", []), ("c", "pending", []), ("d", "pending", ["a"]), ("e", "pending", [])
    )
    assert [s.step_key for s in schedule(steps, max_running=2).start] == ["b"]  # one slot is free
    assert [s.step_key for s in schedule(steps, max_running=3).start] == ["b", "c"]  # d waits on a, e is third
    assert [s.step_key for s in schedule(steps, max_running=9).start] == ["b", "c", "e"]
    assert schedule(steps, max_running=1).start == []  # at the cap
    assert schedule(steps, max_running=2).readiness["d"].state == "waiting"


def test_a_step_behind_a_blocked_step_is_blocked_and_the_reason_names_the_failed_one() -> None:
    steps = plan(
        ("a", "failed", []), ("b", "running", []), ("c", "pending", ["a"]), ("d", "pending", ["c"]),
        ("e", "pending", ["c", "b"]), ("f", "pending", ["b"]), ("g", "pending", []),
    )
    result = schedule(steps, max_running=3)
    states = {k: r.state for k, r in result.readiness.items()}
    assert states == {"c": "blocked", "d": "blocked", "e": "blocked", "f": "waiting", "g": "ready"}
    assert result.readiness["c"].reason == "blocked by a (failed)"
    assert result.readiness["d"].reason == "blocked by c (blocked), because a (failed)"
    assert result.readiness["e"].waiting_on == ("b",) and result.readiness["e"].because == (("a", "failed"),)
    assert [s.step_key for s in result.start] == ["g"]  # independent work keeps being scheduled
