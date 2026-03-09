"""Tests for ready-all task overview summarization helpers."""

from app.services.task_overview_summary import (
    build_actionable_ready_summary,
    extract_ready_task_candidates,
    parse_task_overview_stats,
)


def test_parse_task_overview_stats_reads_headline_counts() -> None:
    overview = "READY-ALL[12 ready, 2 blocked, 0 active, 1 stale across 5 projects]"

    stats = parse_task_overview_stats(overview)

    assert stats.ready == 12
    assert stats.blocked == 2
    assert stats.active == 0
    assert stats.stale == 1
    assert stats.projects == 5


def test_extract_ready_task_candidates_ignores_non_ready_rows() -> None:
    overview = """READY-ALL[2 ready, 1 blocked, 1 active, 1 stale across 1 projects]

agent-hub (2 ready, 1 blocked, 1 active, 1 stale)
  ~ task-live123 P2 refactor [A] Live refactor lane [running]
  ? task-stale12 P2 task     [M] Stale task [stale-running]
  ! task-block99 P1 bug      [A] Blocked bug
    task-52831804 P3 refactor [A] Refactor: backend/app/services/tools/_executor_consultation.py
  * task-0e20ca4d P2 bug      [A] Fix memory selection drift
"""

    candidates = extract_ready_task_candidates(overview)

    assert [candidate.task_id for candidate in candidates] == [
        "task-52831804",
        "task-0e20ca4d",
    ]


def test_build_actionable_ready_summary_limits_per_project() -> None:
    overview = """READY-ALL[3 ready, 0 blocked, 0 active, 0 stale across 1 projects]

agent-hub (3 ready)
    task-1aaaaaaa P3 refactor [A] First
    task-2bbbbbbb P3 refactor [A] Second
    task-3ccccccc P3 refactor [A] Third
"""

    summary = build_actionable_ready_summary(overview, per_project_limit=2)

    assert "ACTIONABLE-READY[2]" in summary
    assert "task-1aaaaaaa" in summary
    assert "task-2bbbbbbb" in summary
    assert "task-3ccccccc" not in summary
