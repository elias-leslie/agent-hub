"""Per-run git worktree and run directory.

``<runs_root>/<run_id>/worktree`` is a git worktree of the run's repository on its own branch;
``<runs_root>/<run_id>/run`` holds packets, full step notes and transcript references. A run without
a repository gets a plain working directory and no checkpoints.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.utils.safe_subprocess import create_process

from .packet import GitState


class GitError(RuntimeError):
    pass


async def _git(cwd: Path, *args: str, config: tuple[str, ...] = ()) -> str:
    argv = ["git", *(a for pair in config for a in ("-c", pair)), *args]
    proc = await create_process(*argv, working_dir=cwd)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {err.decode(errors='replace').strip()}")
    return out.decode(errors="replace").strip()


async def head_sha(repo: str | Path, ref: str = "HEAD") -> str:
    return await _git(Path(repo), "rev-parse", ref)


@dataclass(frozen=True)
class RunWorkspace:
    root: Path
    repo_path: str | None
    base_sha: str | None
    branch: str
    git_identity: tuple[str, ...] = ()

    @property
    def worktree(self) -> Path:
        return self.root / "worktree"

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

    async def ensure(self) -> None:
        """Create the worktree and run directory if missing (idempotent)."""

        await asyncio.to_thread(self.run_dir.mkdir, parents=True, exist_ok=True)
        if self.worktree.exists():
            return
        if not self.repo_path:
            await asyncio.to_thread(self.worktree.mkdir, parents=True, exist_ok=True)
            return
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
        await _git(
            Path(self.repo_path),
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

    async def checkpoint(self, message: str) -> str | None:
        """Commit everything in the worktree and return the new sha (an empty commit if nothing changed)."""

        if not self.repo_path:
            return None
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
