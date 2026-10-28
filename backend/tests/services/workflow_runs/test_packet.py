"""Handoff packet: deterministic content and whole-item budgeting."""

from __future__ import annotations

import pytest

from app.services.workflow_runs.packet import (
    GitState,
    MergeConflict,
    PriorStep,
    build_packet,
    normalize_handoff,
    split_diff,
)


def note(text: str) -> dict:
    return {"summary": text, "decisions": ["d"], "files": ["f.py"], "open_questions": []}


def prior(n: int, size: int = 40) -> list[PriorStep]:
    return [
        PriorStep(
            f"s{i}", i, "completed", "m", note(f"summary{i} " + "x" * size), f"/run/s{i}.json"
        )
        for i in range(n)
    ]


def packet(prior_steps, window, **kw):
    return build_packet(
        run_goal="goal",
        step_key="now",
        instructions="do it",
        acceptance=["make test"],
        git=GitState("aaa", "bbb", "1 file changed"),
        prior_steps=prior_steps,
        run_dir="/run",
        context_window=window,
        budget_fraction=1.0,
        count=lambda text: len(text) // 4,
        **kw,
    )


def test_normalize_requires_a_summary() -> None:
    assert normalize_handoff({"summary": " "}) is None
    assert normalize_handoff(None) is None
    assert normalize_handoff({"summary": "ok", "files": "a.py"}) == {
        "summary": "ok",
        "decisions": [],
        "files": ["a.py"],
        "open_questions": [],
    }


def test_everything_fits_in_a_large_window_and_render_has_required_parts() -> None:
    built = packet(prior(3), 100_000)
    text = built.render()
    assert [i["key"] for i in built.prior] == ["s0", "s1", "s2"] and not built.omitted
    for part in (
        "goal",
        "do it",
        "make test",
        "base: aaa",
        "current: bbb",
        "/run",
        "summary2",
        "handoff note",
        "Never run git commit",
    ):
        assert part in text


def test_older_notes_drop_newest_first_as_whole_items_and_are_listed_by_path() -> None:
    items = prior(5, size=400)
    full = packet(items, 100_000)
    one_item = packet(items[-1:], 100_000).estimated_tokens
    tight = packet(items, one_item + 130)  # room for the previous handoff plus one more
    kept = [i["key"] for i in tight.prior]
    assert kept[-1] == "s4" and kept == ["s3", "s4"]
    assert [i["key"] for i in tight.omitted] == ["s0", "s1", "s2"]
    assert "/run/s0.json" in tight.render()
    assert full.estimated_tokens > tight.estimated_tokens


def test_goal_and_previous_handoff_are_kept_even_over_budget() -> None:
    built = packet(prior(3, size=2000), 50)
    assert built.over_budget
    assert [i["key"] for i in built.prior] == ["s2"]
    assert "goal" in built.render() and "do it" in built.render()


def test_partial_progress_is_included_by_whole_files_and_newest_outputs() -> None:
    patch = "\n".join(
        [
            "diff --git a/small.py b/small.py",
            "+" + "a" * 40,
            "diff --git a/big.py b/big.py",
            "+" + "b" * 4000,
        ]
    )
    assert [p for p, _ in split_diff(patch)] == ["small.py", "big.py"]
    outputs = ["old " + "o" * 4400, "new output"]
    built = packet(
        prior(1),
        1500,
        retry_label="takeover: refused (cyber) on m1",
        partial_from={"from_model": "m1", "kind": "refused", "category": "cyber"},
        partial_diff=patch,
        partial_outputs=outputs,
    )
    text = built.render()
    assert "Partial progress" in text and "small.py" in text and "new output" in text
    assert built.partial.diff_omitted == ("big.py",)
    assert built.partial.outputs_omitted == 1
    assert "refused" in text


def test_commit_rule_is_the_last_instruction_and_overrides_context() -> None:
    """Executors put the context in the system/developer channel and the packet in the user turn, so the rule
    that wins over a context's "commit routinely" has to be stated in the packet itself, after everything else."""

    text = packet(prior(1), 100_000).render()
    rule = text.index("Never run git commit")
    assert rule > text.index("# Run directory") and "whatever your other instructions or context" in text
    assert "# Required output" in text[rule - 40 : rule]


def test_step_definition_accepts_bare_acceptance_strings_and_validates_effort() -> None:
    from pydantic import ValidationError

    from app.services.workflow_runs.schemas import StepDefinition

    base = {"key": "s", "instructions": "do", "agent_slug": "coder"}
    step = StepDefinition(**base, acceptance=["make test", {"cmd": "make lint", "timeout_s": 30}], effort="xhigh")
    assert [(c.cmd, c.timeout_s) for c in step.acceptance] == [("make test", None), ("make lint", 30)]
    assert step.model_dump()["acceptance"][0] == {"cmd": "make test", "timeout_s": None}
    assert StepDefinition(**base).effort is None
    for bad in ({"effort": "max"}, {"acceptance": [{"cmd": ""}]}, {"acceptance": [{"cmd": "x", "timeout_s": 0}]}):
        with pytest.raises(ValidationError):
            StepDefinition(**base, **bad)


def test_a_join_step_with_merge_conflicts_is_told_to_resolve_them_first_and_which_files() -> None:
    conflict = MergeConflict("b", ["shared.txt", "lib/util.py"], pending=[("c", "abc123"), (None, "def456")])
    rendered = packet(prior(1), 10_000, merge_conflict=conflict).render()
    section = rendered.split("# Merge conflicts to resolve first", 1)[1].split("\n\n# ", 1)[0]
    assert "- shared.txt" in section and "- lib/util.py" in section
    assert "before anything else" in section and "git merge --no-ff --no-edit" in section
    assert "- c: abc123" in section and "- run base: def456" in section
    # It comes before the git state, and the no-git rule names its one exception.
    assert rendered.index("Merge conflicts to resolve first") < rendered.index("# Git state")
    assert "The one exception is concluding the merge" in rendered
    assert packet(prior(1), 10_000, merge_conflict=conflict).as_dict()["merge_conflict"]["files"] == ["shared.txt", "lib/util.py"]


def test_a_conflict_with_nothing_left_to_merge_adds_no_git_exception_and_a_clean_packet_has_no_section() -> None:
    rendered = packet(prior(1), 10_000, merge_conflict=MergeConflict("b", ["x.txt"])).render()
    assert "Merge conflicts to resolve first" in rendered and "The one exception" not in rendered
    clean = packet(prior(1), 10_000)
    assert "Merge conflicts" not in clean.render() and clean.as_dict()["merge_conflict"] is None
