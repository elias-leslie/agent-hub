"""Tests for git status summarization helpers."""

from app.services.git_status_summary import (
    build_actionable_git_summary,
    parse_git_status_rows,
)


def test_parse_git_status_rows_reads_compact_output() -> None:
    git_status = """GIT[3]
summitflow      main            clean   uncommitted:0 ahead:0 behind:0
agent-hub       main            dirty   uncommitted:14 ahead:2 behind:0
terminal        main            behind  uncommitted:0 ahead:0 behind:3
"""

    rows = parse_git_status_rows(git_status)

    assert [(row.project_id, row.state, row.uncommitted, row.ahead, row.behind) for row in rows] == [
        ("summitflow", "clean", 0, 0, 0),
        ("agent-hub", "dirty", 14, 2, 0),
        ("terminal", "behind", 0, 0, 3),
    ]


def test_build_actionable_git_summary_formats_next_actions() -> None:
    git_status = """GIT[4]
summitflow      main            clean   uncommitted:0 ahead:0 behind:0
agent-hub       main            dirty   uncommitted:14 ahead:2 behind:0
terminal        main            dirty   uncommitted:2 ahead:0 behind:0
portfolio-ai    main            ahead   uncommitted:0 ahead:5 behind:0
"""

    summary = build_actionable_git_summary(git_status)

    assert "ACTIONABLE-GIT[3]" in summary
    assert "agent-hub | branch=main | state=dirty | uncommitted=14 | ahead=2 | behind=0 | next=inspect_then_publish" in summary
    assert "terminal | branch=main | state=dirty | uncommitted=2 | ahead=0 | behind=0 | next=inspect_then_commit_or_dispatch" in summary
    assert "portfolio-ai | branch=main | state=ahead | uncommitted=0 | ahead=5 | behind=0 | next=publish_pending_commits" in summary


def test_build_actionable_git_summary_empty_when_all_clean() -> None:
    git_status = """GIT[2]
summitflow      main            clean   uncommitted:0 ahead:0 behind:0
.claude         main            clean   uncommitted:0 ahead:0 behind:0
"""

    assert build_actionable_git_summary(git_status) == ""
