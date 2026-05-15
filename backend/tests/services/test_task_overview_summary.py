"""Tests for ready-all task overview summarization helpers."""

from app.services.task_overview_summary import (
    build_actionable_ready_summary,
    build_actionable_ready_summary_from_payload,
    build_actionable_stale_summary,
    build_actionable_stale_summary_from_payload,
    build_compact_task_overview,
    build_compact_task_overview_from_payload,
    collect_visible_task_ids_from_payload,
    extract_completion_summary_from_payload,
    extract_ready_task_candidates,
    extract_stale_task_candidates_from_payload,
    has_dirty_completion_blocker,
    has_unknown_completion_blocker,
    parse_task_overview_stats,
    parse_task_overview_stats_from_payload,
    should_allow_completion_reconcile_despite_dirty_worktree,
    should_suppress_step_999_auto_defect,
    summarize_completion_blockers,
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


def test_build_actionable_stale_summary_emits_stale_rows() -> None:
    overview = """READY-ALL[1 ready, 0 blocked, 0 active, 2 stale across 1 projects]

agent-hub (1 ready, 2 stale)
  ? task-stale001 P2 task     [M] Stale task one [stale-running]
  ? task-stale002 P3 refactor [A] Stale task two [stale-running]
    task-ready001 P2 bug      [A] Ready task
"""

    summary = build_actionable_stale_summary(overview, per_project_limit=2)

    assert "ACTIONABLE-STALE[2]" in summary
    assert "task-stale001" in summary
    assert "task-stale002" in summary


def test_build_compact_task_overview_preserves_blocked_and_stale_sections() -> None:
    overview = """READY-ALL[1 ready, 1 blocked, 1 active, 1 stale across 1 projects]

agent-hub (1 ready, 1 blocked, 1 active, 1 stale)
  ~ task-live001 P2 task     [M] Live lane [running]
  ? task-stale001 P3 task     [M] Stale lane [stale-running]
  ! task-block001 P1 bug      [A] Blocked fix
    task-ready001 P2 refactor [A] Ready refactor
"""

    summary = build_compact_task_overview(overview, per_project_limit=2)

    assert "ACTIONABLE-READY[1]" in summary
    assert "ACTIONABLE-BLOCKED[1]" in summary
    assert "ACTIONABLE-STALE[1]" in summary
    assert "task-block001" in summary
    assert "task-stale001" in summary


def test_parse_task_overview_stats_from_payload_reads_summary_counts() -> None:
    payload = {
        "summary": {
            "ready": 4,
            "blocked": 1,
            "active": 2,
            "stale": 3,
            "projects": 2,
        },
        "projects": [],
    }

    stats = parse_task_overview_stats_from_payload(payload)

    assert stats.ready == 4
    assert stats.blocked == 1
    assert stats.active == 2
    assert stats.stale == 3
    assert stats.projects == 2


def test_build_compact_task_overview_from_payload_matches_existing_contract() -> None:
    payload = {
        "summary": {"ready": 2, "blocked": 1, "active": 1, "stale": 1, "projects": 1},
        "projects": [
            {
                "project_id": "agent-hub",
                "ready_count": 2,
                "blocked_count": 1,
                "active_count": 1,
                "stale_count": 1,
                "ready_tasks": [
                    {
                        "id": "task-ready001",
                        "priority": 2,
                        "task_type": "refactor",
                        "execution_mode": "autonomous",
                        "title": "Ready refactor",
                    },
                    {
                        "id": "task-ready002",
                        "priority": 1,
                        "task_type": "bug",
                        "execution_mode": "manual",
                        "title": "Ready fix",
                    },
                ],
                "blocked_tasks": [
                    {
                        "id": "task-block001",
                        "priority": 1,
                        "task_type": "bug",
                        "execution_mode": "autonomous",
                        "title": "Blocked fix",
                    }
                ],
                "active_tasks": [
                    {
                        "id": "task-live001",
                        "priority": 2,
                        "task_type": "task",
                        "execution_mode": "manual",
                        "title": "Live lane",
                    }
                ],
                "stale_tasks": [
                    {
                        "id": "task-stale001",
                        "priority": 3,
                        "task_type": "task",
                        "execution_mode": "manual",
                        "title": "Stale lane",
                    }
                ],
            }
        ],
    }

    summary = build_compact_task_overview_from_payload(payload, per_project_limit=2)

    assert "READY-ALL[2 ready, 1 blocked, 1 active, 1 stale across 1 projects]" in summary
    assert "PROJECTS[1]" in summary
    assert "- agent-hub | 2 ready, 1 blocked, 1 active, 1 stale" in summary
    assert "ACTIONABLE-READY[2]" in summary
    assert "- agent-hub | task-ready001 | P2 refactor [A] | Ready refactor" in summary
    assert "- agent-hub | task-ready002 | P1 bug [M] | Ready fix" in summary
    assert "ACTIONABLE-BLOCKED[1]" in summary
    assert "ACTIONABLE-STALE[1]" in summary


def test_payload_task_helpers_collect_visible_ids_and_stale_candidates() -> None:
    payload = {
        "summary": {"ready": 1, "blocked": 0, "active": 1, "stale": 2, "projects": 1},
        "projects": [
            {
                "project_id": "agent-hub",
                "ready_count": 1,
                "blocked_count": 0,
                "active_count": 1,
                "stale_count": 2,
                "ready_tasks": [
                    {
                        "id": "task-ready001",
                        "priority": 2,
                        "task_type": "refactor",
                        "execution_mode": "autonomous",
                        "title": "Ready refactor",
                    }
                ],
                "blocked_tasks": [],
                "active_tasks": [
                    {
                        "id": "task-live001",
                        "priority": 2,
                        "task_type": "task",
                        "execution_mode": "manual",
                        "title": "Live lane",
                    }
                ],
                "stale_tasks": [
                    {
                        "id": "task-stale001",
                        "priority": 2,
                        "task_type": "task",
                        "execution_mode": "manual",
                        "title": "Stale lane one",
                    },
                    {
                        "id": "task-stale002",
                        "priority": 3,
                        "task_type": "refactor",
                        "execution_mode": "autonomous",
                        "title": "Stale lane two",
                    },
                ],
            }
        ],
    }

    visible_task_ids = collect_visible_task_ids_from_payload(payload)
    stale_candidates = extract_stale_task_candidates_from_payload(payload)
    stale_summary = build_actionable_stale_summary_from_payload(payload, per_project_limit=1)
    ready_summary = build_actionable_ready_summary_from_payload(payload)

    assert visible_task_ids == {
        "task-ready001",
        "task-live001",
        "task-stale001",
        "task-stale002",
    }
    assert [candidate.task_id for candidate in stale_candidates] == ["task-stale001", "task-stale002"]
    assert "ACTIONABLE-STALE[1]" in stale_summary
    assert "task-stale001" in stale_summary
    assert "task-stale002" not in stale_summary
    assert "ACTIONABLE-READY[1]" in ready_summary


def test_payload_completion_summary_surfaces_dirty_and_unknown_blockers() -> None:
    payload = {
        "summary": {"ready": 3, "blocked": 0, "active": 0, "stale": 0, "projects": 1},
        "projects": [
            {
                "project_id": "agent-hub",
                "ready_count": 3,
                "blocked_count": 0,
                "active_count": 0,
                "stale_count": 0,
                "ready_tasks": [
                    {
                        "id": "task-a2178df4",
                        "priority": 2,
                        "task_type": "task",
                        "execution_mode": "autonomous",
                        "title": "Completion-ready lane",
                        "completion_readiness": {"ready": True, "reason": None},
                    },
                    {
                        "id": "task-c4fbbd9d",
                        "priority": 2,
                        "task_type": "bug",
                        "execution_mode": "autonomous",
                        "title": "Unknown closure lane",
                        "completion_readiness": {"ready": False, "reason": "unknown"},
                    },
                    {
                        "id": "task-dirty001",
                        "priority": 2,
                        "task_type": "task",
                        "execution_mode": "autonomous",
                        "title": "Dirty closure lane",
                        "completion_readiness": {
                            "ready": False,
                            "reason": "claimed checkout has uncommitted changes",
                        },
                    },
                ],
                "blocked_tasks": [],
                "active_tasks": [],
                "stale_tasks": [],
            }
        ],
    }

    completion_summary = extract_completion_summary_from_payload(payload)

    assert "COMPLETION-READY[1 ready, 1 blocked, 1 unknown]" in completion_summary
    assert "COMPLETION-BLOCKERS[claimed checkout has uncommitted changes]" in completion_summary
    assert has_dirty_completion_blocker(payload) is True
    assert has_unknown_completion_blocker(payload) is True
    assert should_allow_completion_reconcile_despite_dirty_worktree(payload) is True
    assert should_suppress_step_999_auto_defect(payload) is True
    assert summarize_completion_blockers(payload) == ("claimed checkout has uncommitted changes",)


def test_compact_payload_overview_includes_completion_summary() -> None:
    payload = {
        "summary": {"ready": 1, "blocked": 0, "active": 0, "stale": 0, "projects": 1},
        "projects": [
            {
                "project_id": "agent-hub",
                "ready_count": 1,
                "blocked_count": 0,
                "active_count": 0,
                "stale_count": 0,
                "ready_tasks": [
                    {
                        "id": "task-ready001",
                        "priority": 2,
                        "task_type": "task",
                        "execution_mode": "autonomous",
                        "title": "Closure ready",
                        "completion_readiness": {"ready": True, "reason": None},
                    }
                ],
                "blocked_tasks": [],
                "active_tasks": [],
                "stale_tasks": [],
            }
        ],
    }

    summary = build_compact_task_overview_from_payload(payload)

    assert "completion=1 closure-ready" in summary
    assert "COMPLETION-READY[1 ready]" in summary
