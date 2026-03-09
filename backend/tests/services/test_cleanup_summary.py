"""Tests for cleanup status summarization helpers."""

from app.services.cleanup_summary import (
    build_actionable_cleanup_summary,
    extract_cleanup_action_items,
)


def test_extract_cleanup_action_items_finds_finalize_conflict_and_review_tasks() -> None:
    status = """CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=1 dirty=0 orphan=3 prunable=0
summitflow worktrees:1 dirty:0 orphan:3 prunable:0 tasks:task-aa44180c finalize:task-aa44180c conflicts:task-bb22cc33 review:task-dd44ee55
"""

    items = extract_cleanup_action_items(status)

    assert [(item.project_id, item.kind, item.task_id) for item in items] == [
        ("summitflow", "finalize", "task-aa44180c"),
        ("summitflow", "conflicts", "task-bb22cc33"),
        ("summitflow", "review", "task-dd44ee55"),
    ]


def test_build_actionable_cleanup_summary_formats_items() -> None:
    status = """CLEANUP[current]:repos=1 needs_cleanup=1 worktrees=1 dirty=0 orphan=3 prunable=0
summitflow worktrees:1 dirty:0 orphan:3 prunable:0 tasks:task-aa44180c finalize:task-aa44180c
"""

    summary = build_actionable_cleanup_summary(status)

    assert "ACTIONABLE-CLEANUP[1]" in summary
    assert "- summitflow | finalize | task-aa44180c" in summary
