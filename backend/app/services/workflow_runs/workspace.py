"""Per-run git worktree, per-step lanes and the run directory.

``<runs_root>/<run_id>/worktree`` is a git worktree of the run's repository on the run's branch
(``workflow/<run8>``); ``<runs_root>/<run_id>/run`` holds packets, full step notes and transcript references. A run
without a repository gets a plain working directory and no checkpoints.

A run that runs one step at a time works in that worktree: every step checkpoints on the run branch, so the finished
run's code is the branch tip and the worktree.

A run that may run steps at once gives each running step a lane: ``<runs_root>/<run_id>/lanes/<step>`` on the branch
``workflow/<run8>-<step>``, started from the checkpoints of the step's dependencies (the first one, then each other one
merged in with no fast-forward). A conflict is kept in the lane for the step to resolve; nothing is resolved for it.
A finished step's lane directory is removed, its branch and commits stay. When the run completes, the leaf steps'
checkpoints are brought together on the run branch (``integrate``), so the result is in the same place either way.
When the run ends (completed, failed or cancelled) its own worktree is removed the same way (``release``): the branch
and its commits stay, and a worktree with uncommitted changes is left where it is and reported.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.utils.safe_subprocess import create_process

from .packet import GitState


class GitError(RuntimeError):
    pass


async def _git_rc(cwd: Path, *args: str, config: tuple[str, ...] = ()) -> tuple[int, str, str]:
    """Run git and return (exit code, stdout, stderr) without judging the exit code."""

    argv = ["git", *(a for pair in config for a in ("-c", pair)), *args]
    proc = await create_process(*argv, working_dir=cwd)
    out, err = await proc.communicate()
    return (
        proc.returncode if proc.returncode is not None else -1,
        out.decode(errors="replace").strip(),
        err.decode(errors="replace").strip(),
    )


async def _git(cwd: Path, *args: str, config: tuple[str, ...] = ()) -> str:
    code, out, err = await _git_rc(cwd, *args, config=config)
    if code != 0:
        raise GitError(f"git {' '.join(args)} failed: {err}")
    return out


# Adding or removing worktrees of one repository takes turns inside this process; git also locks its own records.
_REPO_LOCKS: dict[str, asyncio.Lock] = {}


def _repo_lock(repo: str | Path) -> asyncio.Lock:
    return _REPO_LOCKS.setdefault(str(repo), asyncio.Lock())

CONFLICT_MARKER = "<<<<<<< "


async def head_sha(repo: str | Path, ref: str = "HEAD") -> str:
    return await _git(Path(repo), "rev-parse", ref)


@dataclass(frozen=True)
class LaneParent:
    """A commit a lane starts from: the checkpoint of a dependency (``step_key`` None: the run's base commit)."""

    step_key: str | None
    sha: str

    def as_dict(self) -> dict[str, Any]:
        return {"step": self.step_key, "sha": self.sha}


@dataclass(frozen=True)
class RunWorkspace:
    root: Path
    repo_path: str | None
    base_sha: str | None
    branch: str
    git_identity: tuple[str, ...] = ()
    # The step this workspace is the lane of; None is the run's own worktree.
    lane: str | None = None

    @property
    def worktree(self) -> Path:
        return self.root / "worktree" if self.lane is None else self.root / "lanes" / self.lane

    @property
    def run_dir(self) -> Path:
        return self.root / "run"

    @classmethod
    def from_meta(cls, meta: dict[str, Any], git_identity: tuple[str, ...] = ()) -> RunWorkspace:
        return cls(
            Path(meta["root"]),
            meta.get("repo_path"),
            meta.get("base_sha"),
            meta["branch"],
            git_identity,
        )

    @classmethod
    def lane_of(
        cls,
        meta: dict[str, Any],
        step_key: str,
        git_identity: tuple[str, ...] = (),
        base_sha: str | None = None,
    ) -> RunWorkspace:
        """The lane of one step: its own worktree and branch; ``base_sha`` is the commit the lane started from."""

        return cls(
            Path(meta["root"]),
            meta.get("repo_path"),
            base_sha or meta.get("base_sha"),
            f"{meta['branch']}-{step_key}",
            git_identity,
            step_key,
        )

    async def ensure(self) -> None:
        """Create the worktree and run directory if missing (idempotent)."""

        await asyncio.to_thread(self.run_dir.mkdir, parents=True, exist_ok=True)
        if self.worktree.exists():
            return
        if not self.repo_path:
            await asyncio.to_thread(self.worktree.mkdir, parents=True, exist_ok=True)
            return
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
        repo = Path(self.repo_path)
        code, _out, _err = await _git_rc(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{self.branch}")
        if self.lane is None and code == 0:
            # A branch that is already there (a finished run taking new work, its worktree removed) keeps its commits.
            await _git(repo, "worktree", "prune")
            await _git(repo, "worktree", "add", str(self.worktree), self.branch)
            return
        await _git(
            repo,
            "worktree",
            "add",
            "-B",
            self.branch,
            str(self.worktree),
            self.base_sha or "HEAD",
        )

    async def current_sha(self) -> str | None:
        return await head_sha(self.worktree) if self.repo_path else None

    async def git_state(self) -> GitState:
        if not self.repo_path:
            return GitState()
        await _git(self.worktree, "add", "-A")
        stat = await _git(self.worktree, "diff", "--stat", "--cached", self.base_sha or "HEAD")
        return GitState(self.base_sha, await self.current_sha(), stat)

    async def diff_since(self, sha: str | None) -> str:
        """Full patch of everything changed in the worktree since ``sha`` (committed or not)."""

        if not self.repo_path:
            return ""
        await _git(self.worktree, "add", "-A")
        return await _git(self.worktree, "diff", "--cached", sha or self.base_sha or "HEAD")

    async def read_json(self, path: str) -> Any:
        return await asyncio.to_thread(lambda: json.loads(Path(path).read_text()))

    async def checkpoint(self, message: str, *, conflict_files: Sequence[str] = ()) -> str | None:
        """Commit everything in the worktree and return the new sha (an empty commit if nothing changed).

        A lane that started from a conflicted merge is committed only once those files no longer hold conflict
        markers; the commit then also completes the merge.
        """

        if not self.repo_path:
            return None
        left = await self.unresolved(conflict_files)
        if left:
            raise GitError(f"merge conflicts not resolved in {', '.join(left)}")
        await _git(self.worktree, "add", "-A")
        await _git(
            self.worktree, "commit", "--allow-empty", "-m", message, config=self.git_identity
        )
        return await self.current_sha()

    async def reset(self, sha: str | None) -> None:
        """Return the worktree to a checkpoint, discarding anything the failed attempt left behind."""

        if not self.repo_path or not sha:
            return
        await _git(self.worktree, "reset", "--hard", sha)
        await _git(self.worktree, "clean", "-fd")

    async def write_note(self, relative: str, payload: Any) -> str:
        path = self.run_dir / relative
        text = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, indent=2, sort_keys=True, default=str)
        )

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

        await asyncio.to_thread(_write)
        return str(path)

    # --- lanes ---------------------------------------------------------------------------------------------------

    async def unresolved(self, files: Sequence[str]) -> list[str]:
        """The files of a conflicted merge that still hold conflict markers."""

        if not files:
            return []

        def scan() -> list[str]:
            left = []
            for name in files:
                path = self.worktree / name
                try:
                    text = path.read_text(errors="replace")
                except OSError:
                    continue  # deleted by the resolution
                if any(line.startswith(CONFLICT_MARKER) for line in text.splitlines()):
                    left.append(name)
            return left

        return await asyncio.to_thread(scan)

    async def prepare_lane(self, parents: Sequence[LaneParent]) -> dict[str, Any]:
        """Create this lane's worktree from ``parents`` and describe it.

        The branch starts at the first parent; each other parent is merged in with no fast-forward. A merge that
        conflicts stops there, with the conflicted tree left in the lane and the parents not yet merged marked
        ``pending``. Nothing is resolved.
        """

        if self.lane is None or not self.repo_path or not parents:
            raise GitError("a lane needs a repository and at least one parent commit")
        await asyncio.to_thread(self.run_dir.mkdir, parents=True, exist_ok=True)
        first = parents[0]
        async with _repo_lock(self.repo_path):
            await self._drop_worktree()  # a half-made lane from a crash is made again from scratch
            await asyncio.to_thread(self.worktree.parent.mkdir, parents=True, exist_ok=True)
            await _git(Path(self.repo_path), "worktree", "prune")
            await _git(
                Path(self.repo_path), "worktree", "add", "-B", self.branch, str(self.worktree), first.sha
            )
        merges = await self._merge_parents(parents[1:])
        return await self._lane_record(parents, merges)

    async def _merge_parents(self, parents: Sequence[LaneParent]) -> list[dict[str, Any]]:
        merges: list[dict[str, Any]] = []
        conflicted = False
        for parent in parents:
            entry: dict[str, Any] = {"step": parent.step_key, "sha": parent.sha, "files": []}
            if conflicted:
                merges.append({**entry, "result": "pending"})
                continue
            before = await head_sha(self.worktree)
            code, _out, err = await _git_rc(
                self.worktree,
                "merge",
                "--no-ff",
                "--no-edit",
                "-m",
                f"workflow merge {parent.step_key or parent.sha[:8]} into {self.lane}",
                parent.sha,
                config=self.git_identity,
            )
            if code == 0:
                head = await head_sha(self.worktree)
                if head == before:  # the parent was already part of the lane
                    merges.append({**entry, "result": "up_to_date"})
                else:
                    merges.append({**entry, "result": "clean", "merge_sha": head})
                continue
            files = await _git(self.worktree, "diff", "--name-only", "--diff-filter=U")
            if not files:
                raise GitError(f"git merge {parent.sha} failed: {err}")
            conflicted = True
            merges.append({**entry, "result": "conflict", "files": files.splitlines()})
        return merges

    async def _lane_record(
        self, parents: Sequence[LaneParent], merges: list[dict[str, Any]]
    ) -> dict[str, Any]:
        conflict = next((m for m in merges if m["result"] == "conflict"), None)
        files = conflict["files"] if conflict else []
        return {
            "lane": self.lane,
            "worktree": str(self.worktree),
            "branch": self.branch,
            "parents": [p.as_dict() for p in parents],
            "base_sha": parents[0].sha,
            # The commit the step starts from: the merged tree, or none while a conflict is open.
            "start_sha": None if conflict else await head_sha(self.worktree),
            "merge_result": "conflict" if conflict else ("clean" if merges else "none"),
            "merges": merges,
            "conflict_files": files,
        }

    async def reset_lane(self, record: dict[str, Any]) -> dict[str, Any]:
        """Back to where the lane started, discarding what a crashed attempt left; a conflicted start is made again."""

        parents = [LaneParent(p["step"], p["sha"]) for p in record["parents"]]
        if record.get("start_sha"):
            await self.reset(record["start_sha"])
            return record
        await self.reset(parents[0].sha)
        merges = await self._merge_parents(parents[1:])
        return await self._lane_record(parents, merges)

    async def _drop_worktree(self) -> None:
        if self.repo_path and self.worktree.exists():
            code, _out, _err = await _git_rc(
                Path(self.repo_path), "worktree", "remove", "--force", str(self.worktree)
            )
            if code != 0 and self.worktree.exists():
                await asyncio.to_thread(shutil.rmtree, self.worktree, True)

    async def retire_lane(self) -> None:
        """Remove the lane's directory once its step is done; the branch and its commits stay in the repository."""

        if self.lane is None or not self.repo_path:
            return
        async with _repo_lock(self.repo_path):
            await self._drop_worktree()
            await _git(Path(self.repo_path), "worktree", "prune")

    async def release(self) -> dict[str, Any]:
        """Remove the run's own worktree once the run has ended; the branch and its commits stay in the repository.

        Nothing is forced: a worktree with uncommitted changes (or one git will not remove) is left in place and the
        result says why.
        """

        if self.lane is not None or not self.repo_path:
            return {"state": "none"}
        repo = Path(self.repo_path)
        async with _repo_lock(self.repo_path):
            if self.worktree.exists():
                code, out, err = await _git_rc(self.worktree, "status", "--porcelain")
                if code != 0:
                    return {"state": "kept", "reason": f"git status failed: {err}"[:300]}
                if out:
                    files = out.splitlines()
                    return {
                        "state": "kept",
                        "reason": "uncommitted_changes",
                        "detail": f"{len(files)} changed path(s) in the worktree; not removed",
                        "files": [line[3:] for line in files[:20]],
                    }
                code, _out, err = await _git_rc(repo, "worktree", "remove", str(self.worktree))
                if code != 0 and self.worktree.exists():
                    return {"state": "kept", "reason": "remove_failed", "detail": err[:300]}
            await _git(repo, "worktree", "prune")
        return {"state": "removed"}

    async def integrate(self, leaves: Sequence[LaneParent]) -> dict[str, Any]:
        """Bring the finished steps nothing else builds on together on the run branch, in this (the run's) worktree.

        The first leaf becomes the branch tip; each other leaf not already part of it is merged in with no
        fast-forward. A conflict between leaves is aborted and reported, and the branch stays at the last clean
        merge: a join step on those leaves is the way to resolve it.
        """

        if self.lane is not None or not self.repo_path:
            raise GitError("integration happens in the run's own worktree")
        await self.ensure()
        if not leaves:
            return self._result("merged", [], [], await head_sha(self.worktree), [])
        await self.reset(leaves[0].sha)
        merged = [leaves[0].step_key]
        for leaf in leaves[1:]:
            code, _out, _err = await _git_rc(self.worktree, "merge-base", "--is-ancestor", leaf.sha, "HEAD")
            if code == 0:
                merged.append(leaf.step_key)
                continue
            code, _out, err = await _git_rc(
                self.worktree,
                "merge",
                "--no-ff",
                "--no-edit",
                "-m",
                f"workflow result: merge {leaf.step_key}",
                leaf.sha,
                config=self.git_identity,
            )
            if code == 0:
                merged.append(leaf.step_key)
                continue
            files = (await _git(self.worktree, "diff", "--name-only", "--diff-filter=U")).splitlines()
            await _git(self.worktree, "merge", "--abort")
            if not files:
                raise GitError(f"git merge {leaf.sha} failed: {err}")
            left = [p.step_key for p in leaves if p.step_key not in merged]
            return self._result("conflict", merged, left, await head_sha(self.worktree), files)
        return self._result("merged", merged, [], await head_sha(self.worktree), [])

    def _result(
        self, state: str, merged: list[Any], left: list[Any], sha: str, files: list[str]
    ) -> dict[str, Any]:
        return {
            "state": state,
            "branch": self.branch,
            "worktree": str(self.worktree),
            "sha": sha,
            "merged": merged,
            "not_merged": left,
            "conflict_files": files,
        }
