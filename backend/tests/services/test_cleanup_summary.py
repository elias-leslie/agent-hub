"""Tests for cleanup status summarization helpers."""

from app.services.cleanup_summary import (
    CleanupActionItem,
    build_actionable_cleanup_summary,
    build_actionable_cleanup_summary_from_payload,
    extract_cleanup_action_items,
    filter_reconciled_cleanup_items,
)


def test_extract_cleanup_action_items_finds_finalize_conflict_review_and_orphan_tasks() -> None:
    status = """CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=1 dirty=0 orphan=3 prunable=0
summitflow checkpoints:1 dirty:0 orphan:3 prunable:0 tasks:task-aa44180c finalize:task-aa44180c conflicts:task-bb22cc33 review:task-dd44ee55 salvage:task-ff66aa77 review_orphans:task-9988cc77 orphan_branches:task-ee55ff66/main
"""

    items = extract_cleanup_action_items(status)

    assert [(item.project_id, item.kind, item.task_id) for item in items] == [
        ("summitflow", "finalize", "task-aa44180c"),
        ("summitflow", "conflicts", "task-bb22cc33"),
        ("summitflow", "review", "task-dd44ee55"),
        ("summitflow", "salvage", "task-ff66aa77"),
        ("summitflow", "review_orphans", "task-9988cc77"),
        ("summitflow", "orphan_branch", "task-ee55ff66"),
    ]


def test_build_actionable_cleanup_summary_formats_items() -> None:
    status = """CLEANUP[current]:repos=1 needs_cleanup=1 checkpoints=1 dirty=0 orphan=3 prunable=0
summitflow checkpoints:1 dirty:0 orphan:3 prunable:0 tasks:task-aa44180c finalize:task-aa44180c orphan_branches:task-ee55ff66/main
"""

    summary = build_actionable_cleanup_summary(status)

    assert "ACTIONABLE-CLEANUP[2]" in summary
    assert "- summitflow | finalize | task-aa44180c" in summary
    assert "- summitflow | orphan_branch | task-ee55ff66" in summary


def test_build_actionable_cleanup_summary_from_payload_formats_items() -> None:
    payload = {
        "repositories": [
            {
                "project_id": "summitflow",
                "needs_merge_tasks": ["task-aa44180c"],
                "conflict_tasks": [],
                "review_tasks": [],
                "salvage_task_ids": [],
                "review_orphan_task_ids": [],
                "orphan_branch_names": ["task-ee55ff66/main"],
            }
        ]
    }

    summary = build_actionable_cleanup_summary_from_payload(payload)

    assert "ACTIONABLE-CLEANUP[2]" in summary
    assert "- summitflow | finalize | task-aa44180c" in summary
    assert "- summitflow | orphan_branch | task-ee55ff66" in summary


def test_filter_reconciled_cleanup_items_drops_authoritative_superseded_task() -> None:
    items = [
        CleanupActionItem(project_id="agent-hub", kind="review", task_id="task-392c88f5"),
        CleanupActionItem(project_id="agent-hub", kind="review", task_id="task-live1234"),
    ]
    workstream_rows = [
        {
            "project_id": "agent-hub",
            "external_id": "task-392c88f5",
            "workstream_status": "authoritative",
        },
        {
            "project_id": "agent-hub",
            "external_id": "task-392c88f5",
            "workstream_status": "superseded",
        },
        {
            "project_id": "agent-hub",
            "external_id": "task-live1234",
            "workstream_status": "authoritative",
        },
    ]

    filtered = filter_reconciled_cleanup_items(items, workstream_rows)

    assert filtered == [CleanupActionItem(project_id="agent-hub", kind="review", task_id="task-live1234")]


def test_filter_reconciled_cleanup_items_handles_lane_rows_with_branch_context() -> None:
    items = [
        CleanupActionItem(project_id="agent-hub", kind="review", task_id="task-ff895807"),
        CleanupActionItem(project_id="agent-hub", kind="review", task_id="task-live1234"),
    ]
    workstream_rows = [
        {
            "project_id": "agent-hub",
            "external_id": "task-ff895807",
            "current_branch": "task-ff895807/main",
            "status": "completed",
            "workstream_status": "authoritative",
        },
        {
            "project_id": "agent-hub",
            "external_id": "task-ff895807",
            "current_branch": "task-ff895807/old",
            "status": "completed",
            "workstream_status": "superseded",
        },
        {
            "project_id": "agent-hub",
            "external_id": "task-live1234",
            "current_branch": "task-live1234/main",
            "status": "completed",
            "workstream_status": "authoritative",
        },
    ]

    filtered = filter_reconciled_cleanup_items(items, workstream_rows)

    assert filtered == [CleanupActionItem(project_id="agent-hub", kind="review", task_id="task-live1234")]
