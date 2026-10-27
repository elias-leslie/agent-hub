"""Handoff packet: deterministic content and whole-item budgeting."""

from __future__ import annotations

from app.services.workflow_runs.packet import (
    GitState,
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
