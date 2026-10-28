"""Run worktree and step lanes against real git repositories."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from app.services.workflow_runs.workspace import GitError, LaneParent, RunWorkspace, _repo_lock

IDENTITY = ("user.name=Agent Hub Workflow", "user.email=workflow@agent-hub.local")
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, env=ENV, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    (path / "shared.txt").write_text("one\ntwo\nthree\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    return path


def meta_of(tmp_path: Path, repo: Path) -> dict[str, str]:
    root = tmp_path / "runs" / "r1"
    return {"root": str(root), "repo_path": str(repo), "base_sha": git(repo, "rev-parse", "HEAD"), "branch": "workflow/r1abcdef"}


def lane(meta: dict[str, str], key: str) -> RunWorkspace:
    return RunWorkspace.lane_of(meta, key, IDENTITY)


async def checkpoint_from(meta: dict[str, str], key: str, base: LaneParent, files: dict[str, str]) -> LaneParent:
    """A finished step: a lane from ``base`` with the files written, checkpointed, and its directory retired."""

    workspace = lane(meta, key)
    await workspace.prepare_lane([base])
    for name, text in files.items():
        (workspace.worktree / name).write_text(text)
    sha = await workspace.checkpoint(f"workflow {key}")
    await workspace.retire_lane()
    assert sha is not None
    return LaneParent(key, sha)


async def test_a_lane_with_one_dependency_starts_at_its_checkpoint_on_its_own_branch(tmp_path, repo) -> None:
    meta = meta_of(tmp_path, repo)
    a = await checkpoint_from(meta, "a", LaneParent(None, meta["base_sha"]), {"a.txt": "a\n"})
    workspace = lane(meta, "b")
    record = await workspace.prepare_lane([a])
    assert workspace.worktree == tmp_path / "runs" / "r1" / "lanes" / "b"
    assert record["branch"] == "workflow/r1abcdef-b" and record["worktree"] == str(workspace.worktree)
    assert (record["base_sha"], record["start_sha"], record["merge_result"], record["merges"]) == (a.sha, a.sha, "none", [])
    assert git(workspace.worktree, "rev-parse", "--abbrev-ref", "HEAD") == "workflow/r1abcdef-b"
    assert (workspace.worktree / "a.txt").read_text() == "a\n"


async def test_dependencies_on_different_files_merge_cleanly_without_a_fast_forward(tmp_path, repo) -> None:
    meta = meta_of(tmp_path, repo)
    base = LaneParent(None, meta["base_sha"])
    a = await checkpoint_from(meta, "a", base, {"a.txt": "a\n"})
    b = await checkpoint_from(meta, "b", base, {"b.txt": "b\n"})
    c = await checkpoint_from(meta, "c", base, {"c.txt": "c\n"})
    join = lane(meta, "join")
    record = await join.prepare_lane([a, b, c])
    assert record["merge_result"] == "clean" and [m["result"] for m in record["merges"]] == ["clean", "clean"]
    assert record["base_sha"] == a.sha and record["start_sha"] == git(join.worktree, "rev-parse", "HEAD")
    assert all((join.worktree / f"{n}.txt").exists() for n in "abc")
    # Two merge commits, each with both parents (no fast-forward), starting from a.
    assert git(join.worktree, "rev-list", "--merges", "--count", "HEAD") == "2"
    assert git(join.worktree, "rev-list", "--first-parent", "-n", "3", "HEAD").splitlines()[-1] == a.sha


async def test_a_dependency_already_part_of_the_lane_is_up_to_date(tmp_path, repo) -> None:
    meta = meta_of(tmp_path, repo)
    a = await checkpoint_from(meta, "a", LaneParent(None, meta["base_sha"]), {"a.txt": "a\n"})
    b = await checkpoint_from(meta, "b", a, {"b.txt": "b\n"})
    record = await lane(meta, "join").prepare_lane([b, a])
    assert [m["result"] for m in record["merges"]] == ["up_to_date"] and record["merge_result"] == "clean"


async def test_a_conflict_is_kept_for_the_step_and_later_dependencies_wait(tmp_path, repo) -> None:
    meta = meta_of(tmp_path, repo)
    base = LaneParent(None, meta["base_sha"])
    a = await checkpoint_from(meta, "a", base, {"shared.txt": "one\nTWO from a\nthree\n"})
    b = await checkpoint_from(meta, "b", base, {"shared.txt": "one\nTWO from b\nthree\n"})
    c = await checkpoint_from(meta, "c", base, {"c.txt": "c\n"})
    join = lane(meta, "join")
    record = await join.prepare_lane([a, b, c])
    assert record["merge_result"] == "conflict" and record["start_sha"] is None
    assert record["conflict_files"] == ["shared.txt"]
    assert [(m["step"], m["result"]) for m in record["merges"]] == [("b", "conflict"), ("c", "pending")]
    text = (join.worktree / "shared.txt").read_text()
    assert "<<<<<<<" in text and "TWO from a" in text and "TWO from b" in text  # kept, not resolved
    assert not (join.worktree / "c.txt").exists()
    assert await join.unresolved(record["conflict_files"]) == ["shared.txt"]

    # The runner will not checkpoint a tree that still has markers, and does once the step has resolved them.
    with pytest.raises(GitError, match=r"shared\.txt"):
        await join.checkpoint("join", conflict_files=record["conflict_files"])
    (join.worktree / "shared.txt").write_text("one\nTWO from both\nthree\n")
    sha = await join.checkpoint("join", conflict_files=record["conflict_files"])
    assert git(join.worktree, "rev-list", "--parents", "-n", "1", sha).split() == [sha, a.sha, b.sha]


async def test_resetting_a_conflicted_lane_makes_the_same_conflict_again(tmp_path, repo) -> None:
    meta = meta_of(tmp_path, repo)
    base = LaneParent(None, meta["base_sha"])
    a = await checkpoint_from(meta, "a", base, {"shared.txt": "one\nA\nthree\n"})
    b = await checkpoint_from(meta, "b", base, {"shared.txt": "one\nB\nthree\n"})
    join = lane(meta, "join")
    record = await join.prepare_lane([a, b])
    (join.worktree / "shared.txt").write_text("half done\n")
    (join.worktree / "junk.txt").write_text("x")
    again = await join.reset_lane(record)
    assert again["merge_result"] == "conflict" and again["conflict_files"] == ["shared.txt"]
    assert "<<<<<<<" in (join.worktree / "shared.txt").read_text() and not (join.worktree / "junk.txt").exists()


async def test_resetting_a_clean_lane_returns_to_the_merged_tree(tmp_path, repo) -> None:
    meta = meta_of(tmp_path, repo)
    base = LaneParent(None, meta["base_sha"])
    a = await checkpoint_from(meta, "a", base, {"a.txt": "a\n"})
    b = await checkpoint_from(meta, "b", base, {"b.txt": "b\n"})
    join = lane(meta, "join")
    record = await join.prepare_lane([a, b])
    (join.worktree / "a.txt").write_text("changed")
    (join.worktree / "junk.txt").write_text("x")
    assert await join.reset_lane(record) == record
    assert (join.worktree / "a.txt").read_text() == "a\n" and not (join.worktree / "junk.txt").exists()
    assert git(join.worktree, "rev-parse", "HEAD") == record["start_sha"]


async def test_retiring_a_lane_removes_the_directory_and_keeps_the_branch_and_commits(tmp_path, repo) -> None:
    meta = meta_of(tmp_path, repo)
    a = await checkpoint_from(meta, "a", LaneParent(None, meta["base_sha"]), {"a.txt": "a\n"})
    assert not (tmp_path / "runs" / "r1" / "lanes" / "a").exists()
    assert git(repo, "rev-parse", "workflow/r1abcdef-a") == a.sha
    assert git(repo, "show", f"{a.sha}:a.txt") == "a"
    assert "lanes" not in git(repo, "worktree", "list")


async def test_a_half_made_lane_is_made_again(tmp_path, repo) -> None:
    meta = meta_of(tmp_path, repo)
    workspace = lane(meta, "a")
    workspace.worktree.mkdir(parents=True)
    (workspace.worktree / "leftover.txt").write_text("x")
    record = await workspace.prepare_lane([LaneParent(None, meta["base_sha"])])
    assert record["start_sha"] == meta["base_sha"] and not (workspace.worktree / "leftover.txt").exists()


async def test_the_result_is_the_leaf_steps_brought_together_on_the_run_branch(tmp_path, repo) -> None:
    meta = meta_of(tmp_path, repo)
    base = LaneParent(None, meta["base_sha"])
    a = await checkpoint_from(meta, "a", base, {"a.txt": "a\n"})
    b = await checkpoint_from(meta, "b", base, {"b.txt": "b\n"})
    run = RunWorkspace.from_meta(meta, IDENTITY)

    one = await run.integrate([a])  # one leaf: the branch tip is its checkpoint
    assert (one["state"], one["sha"], one["merged"]) == ("merged", a.sha, ["a"])
    assert git(repo, "rev-parse", "workflow/r1abcdef") == a.sha and (run.worktree / "a.txt").exists()

    both = await run.integrate([a, b])
    assert (both["state"], both["merged"], both["conflict_files"]) == ("merged", ["a", "b"], [])
    assert all((run.worktree / f"{n}.txt").exists() for n in "ab") and both["branch"] == "workflow/r1abcdef"
    assert git(run.worktree, "rev-parse", "HEAD") == both["sha"]


async def test_leaves_that_conflict_are_reported_and_the_branch_stays_at_the_last_clean_merge(tmp_path, repo) -> None:
    meta = meta_of(tmp_path, repo)
    base = LaneParent(None, meta["base_sha"])
    a = await checkpoint_from(meta, "a", base, {"shared.txt": "one\nA\nthree\n"})
    b = await checkpoint_from(meta, "b", base, {"shared.txt": "one\nB\nthree\n"})
    run = RunWorkspace.from_meta(meta, IDENTITY)
    result = await run.integrate([a, b])
    assert (result["state"], result["merged"], result["not_merged"], result["conflict_files"]) == (
        "conflict",
        ["a"],
        ["b"],
        ["shared.txt"],
    )
    assert result["sha"] == a.sha and git(run.worktree, "status", "--porcelain") == ""  # aborted, clean


async def test_making_and_removing_the_run_worktree_take_turns_on_the_repository_lock(tmp_path, repo) -> None:
    meta = meta_of(tmp_path, repo)
    run = RunWorkspace.from_meta(meta, IDENTITY)
    async with _repo_lock(repo):
        making = asyncio.create_task(run.ensure())
        await asyncio.sleep(0.2)
        assert not making.done() and not run.worktree.exists()  # waits for whoever holds the repository
    await making
    assert run.worktree.exists()
    async with _repo_lock(repo):
        removing = asyncio.create_task(run.release())
        await asyncio.sleep(0.2)
        assert not removing.done() and run.worktree.exists()
    assert (await removing)["state"] == "removed" and not run.worktree.exists()
