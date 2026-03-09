"""Tests for cleanup status summarization helpers."""

from app.services.cleanup_summary import (
    build_actionable_cleanup_summary,
    extract_cleanup_action_items,
)


def test_extract_cleanup_action_items_finds_finalize_conflict_review_and_orphan_tasks() -> None:
    status = """CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=1 dirty=0 orphan=3 prunable=0
summitflow worktrees:1 dirty:0 orphan:3 prunable:0 tasks:task-aa44180c finalize:task-aa44180c conflicts:task-bb22cc33 review:task-dd44ee55 orphan_branches:task-ee55ff66/main
"""

    items = extract_cleanup_action_items(status)

    assert [(item.project_id, item.kind, item.task_id) for item in items] == [
        ("summitflow", "finalize", "task-aa44180c"),
        ("summitflow", "conflicts", "task-bb22cc33"),
        ("summitflow", "review", "task-dd44ee55"),
        ("summitflow", "orphan_branch", "task-ee55ff66"),
    ]


def test_build_actionable_cleanup_summary_formats_items() -> None:
    status = """CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=1 dirty=0 orphan=3 prunable=0
summitflow worktrees:1 dirty:0 orphan:3 prunable:0 tasks:task-aa44180c finalize:task-aa44180c orphan_branches:task-ee55ff66/main
"""

    summary = build_actionable_cleanup_summary(status)

    assert "ACTIONABLE-CLEANUP[2]" in summary
    assert "- summitflow | finalize | task-aa44180c" in summary
    assert "- summitflow | orphan_branch | task-ee55ff66" in summary
