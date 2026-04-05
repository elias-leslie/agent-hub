"""Tests for git status summarization helpers."""

from app.services.git_status_summary import (
    RepoGitStatus,
    build_actionable_git_summary,
    build_actionable_git_summary_from_rows,
    build_compact_git_status,
    parse_git_status_rows,
)


def test_parse_git_status_rows_reads_compact_output() -> None:
    git_status = """GIT[3]
summitflow      main            clean   uncommitted:0 ahead:0 behind:0
agent-hub       main            dirty   uncommitted:14 ahead:2 behind:0
aterm        main            behind  uncommitted:0 ahead:0 behind:3
"""

    rows = parse_git_status_rows(git_status)

    assert [(row.project_id, row.state, row.uncommitted, row.ahead, row.behind) for row in rows] == [
        ("summitflow", "clean", 0, 0, 0),
        ("agent-hub", "dirty", 14, 2, 0),
        ("aterm", "behind", 0, 0, 3),
    ]


def test_build_actionable_git_summary_formats_next_actions() -> None:
    git_status = """GIT[4]
summitflow      main            clean   uncommitted:0 ahead:0 behind:0
agent-hub       main            dirty   uncommitted:14 ahead:2 behind:0
aterm        main            dirty   uncommitted:2 ahead:0 behind:0
portfolio-ai    main            ahead   uncommitted:0 ahead:5 behind:0
"""

    summary = build_actionable_git_summary(git_status)

    assert "ACTIONABLE-GIT[3]" in summary
    assert "agent-hub | branch=main | state=dirty | uncommitted=14 | ahead=2 | behind=0 | next=inspect_then_publish" in summary
    assert "aterm | branch=main | state=dirty | uncommitted=2 | ahead=0 | behind=0 | next=inspect_then_commit_or_dispatch" in summary
    assert "portfolio-ai | branch=main | state=ahead | uncommitted=0 | ahead=5 | behind=0 | next=publish_pending_commits" in summary


def test_build_actionable_git_summary_empty_when_all_clean() -> None:
    git_status = """GIT[2]
summitflow      main            clean   uncommitted:0 ahead:0 behind:0
.claude         main            clean   uncommitted:0 ahead:0 behind:0
"""

    assert build_actionable_git_summary(git_status) == ""


def test_build_compact_git_status_renders_structured_rows() -> None:
    rows = [
        RepoGitStatus(
            project_id="summitflow",
            branch="main",
            state="clean",
            uncommitted=0,
            ahead=0,
            behind=0,
        ),
        RepoGitStatus(
            project_id="agent-hub",
            branch="main",
            state="dirty",
            uncommitted=2,
            ahead=1,
            behind=0,
        ),
    ]

    assert build_compact_git_status(rows) == (
        "GIT[2]\n"
        "summitflow      main            clean   uncommitted:0 ahead:0 behind:0\n"
        "agent-hub       main            dirty   uncommitted:2 ahead:1 behind:0"
    )


def test_build_actionable_git_summary_from_rows_formats_next_actions() -> None:
    rows = [
        RepoGitStatus(
            project_id="agent-hub",
            branch="main",
            state="dirty",
            uncommitted=14,
            ahead=2,
            behind=0,
        ),
        RepoGitStatus(
            project_id="aterm",
            branch="main",
            state="dirty",
            uncommitted=2,
            ahead=0,
            behind=0,
        ),
        RepoGitStatus(
            project_id="portfolio-ai",
            branch="main",
            state="ahead",
            uncommitted=0,
            ahead=5,
            behind=0,
        ),
    ]

    summary = build_actionable_git_summary_from_rows(rows)

    assert "ACTIONABLE-GIT[3]" in summary
    assert "agent-hub | branch=main | state=dirty | uncommitted=14 | ahead=2 | behind=0 | next=inspect_then_publish" in summary
    assert "aterm | branch=main | state=dirty | uncommitted=2 | ahead=0 | behind=0 | next=inspect_then_commit_or_dispatch" in summary
    assert "portfolio-ai | branch=main | state=ahead | uncommitted=0 | ahead=5 | behind=0 | next=publish_pending_commits" in summary
