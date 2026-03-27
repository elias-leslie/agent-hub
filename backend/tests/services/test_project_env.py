"""Tests for project environment resolution.

Verifies that build_project_env() correctly resolves Python virtual environments
for both main repos and git worktrees, and that the resolved environment is
passed to Claude agent subprocesses.

Edge cases covered:
- Main repo with backend/.venv
- Main repo with root .venv
- Git worktree resolving parent's .venv
- Non-Python project (no .venv)
- Missing working directory
- PYTHONHOME removal
- PATH prepending (not appending)
- Worktree with .git file (not directory)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services.tools.project_env import (
    build_project_env,
    build_venv_env_overlay,
    detect_main_repo,
    find_venv,
)


class TestDetectMainRepo:
    """Tests for detect_main_repo() — worktree detection."""

    def test_main_repo_returns_none(self, tmp_path: Path) -> None:
        """Main repo (.git is a directory) → returns None."""
        (tmp_path / ".git").mkdir()
        assert detect_main_repo(tmp_path) is None

    def test_no_git_returns_none(self, tmp_path: Path) -> None:
        """No .git at all → returns None."""
        assert detect_main_repo(tmp_path) is None

    def test_worktree_returns_parent(self, tmp_path: Path) -> None:
        """Worktree (.git is a file) → returns parent repo path."""
        # Set up a fake main repo
        main_repo = tmp_path / "main-repo"
        main_repo.mkdir()
        (main_repo / ".git").mkdir()
        (main_repo / ".git" / "worktrees").mkdir(parents=True)
        (main_repo / ".git" / "worktrees" / "task-abc").mkdir()

        # Set up a fake worktree
        worktree = tmp_path / "worktree-abc"
        worktree.mkdir()
        gitdir = str(main_repo / ".git" / "worktrees" / "task-abc")
        (worktree / ".git").write_text(f"gitdir: {gitdir}\n")

        result = detect_main_repo(worktree)
        assert result is not None
        assert result == main_repo

    def test_worktree_nonexistent_parent_returns_none(self, tmp_path: Path) -> None:
        """Worktree pointing to nonexistent parent → returns None."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / ".git").write_text(
            "gitdir: /nonexistent/path/.git/worktrees/task-xyz\n"
        )
        assert detect_main_repo(worktree) is None

    def test_malformed_gitdir_returns_none(self, tmp_path: Path) -> None:
        """Malformed .git file → returns None."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / ".git").write_text("not a valid gitdir reference\n")
        assert detect_main_repo(worktree) is None

    def test_gitdir_not_worktree_pattern_returns_none(self, tmp_path: Path) -> None:
        """Valid gitdir but not a worktrees path → returns None."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: /some/path/.git/modules/sub\n")
        assert detect_main_repo(worktree) is None


class TestFindVenv:
    """Tests for find_venv() — venv discovery."""

    def test_backend_venv(self, tmp_path: Path) -> None:
        """Finds backend/.venv (priority over root .venv)."""
        venv = tmp_path / "backend" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        result = find_venv(tmp_path)
        assert result == tmp_path / "backend" / ".venv"

    def test_root_venv(self, tmp_path: Path) -> None:
        """Finds root .venv when no backend/.venv."""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        result = find_venv(tmp_path)
        assert result == tmp_path / ".venv"

    def test_backend_venv_preferred_over_root(self, tmp_path: Path) -> None:
        """backend/.venv is preferred over root .venv."""
        for sub in ["backend/.venv/bin", ".venv/bin"]:
            p = tmp_path / sub
            p.mkdir(parents=True)
            (p / "python").write_text("#!/usr/bin/env python3\n")

        result = find_venv(tmp_path)
        assert result == tmp_path / "backend" / ".venv"

    def test_no_venv(self, tmp_path: Path) -> None:
        """No venv found → returns None."""
        assert find_venv(tmp_path) is None

    def test_venv_without_python_binary(self, tmp_path: Path) -> None:
        """Venv dir exists but no bin/python → returns None."""
        (tmp_path / ".venv" / "bin").mkdir(parents=True)
        assert find_venv(tmp_path) is None

    def test_worktree_falls_back_to_main_repo(self, tmp_path: Path) -> None:
        """Worktree has no venv → falls back to main_repo's venv."""
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        venv = main_repo / "backend" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        worktree = tmp_path / "worktree"
        worktree.mkdir()

        result = find_venv(worktree, main_repo=main_repo)
        assert result == main_repo / "backend" / ".venv"

    def test_worktree_own_venv_preferred(self, tmp_path: Path) -> None:
        """If worktree somehow has its own venv, prefer it over main_repo's."""
        main_repo = tmp_path / "main"
        for sub in [main_repo / "backend" / ".venv" / "bin"]:
            sub.mkdir(parents=True)
            (sub / "python").write_text("#!/usr/bin/env python3\n")

        worktree = tmp_path / "worktree"
        wt_venv = worktree / ".venv" / "bin"
        wt_venv.mkdir(parents=True)
        (wt_venv / "python").write_text("#!/usr/bin/env python3\n")

        result = find_venv(worktree, main_repo=main_repo)
        assert result == worktree / ".venv"


class TestBuildProjectEnv:
    """Tests for build_project_env() — full environment building."""

    def test_sets_virtual_env(self, tmp_path: Path) -> None:
        """VIRTUAL_ENV is set to the venv path."""
        venv = tmp_path / "backend" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        env = build_project_env(str(tmp_path))
        assert env["VIRTUAL_ENV"] == str(tmp_path / "backend" / ".venv")

    def test_prepends_venv_bin_to_path(self, tmp_path: Path) -> None:
        """Venv bin is prepended (not appended) to PATH."""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        env = build_project_env(str(tmp_path))
        assert env["PATH"].startswith(str(venv))

    def test_removes_pythonhome(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """PYTHONHOME is removed from the environment."""
        monkeypatch.setenv("PYTHONHOME", "/some/python/home")
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        env = build_project_env(str(tmp_path))
        assert "PYTHONHOME" not in env

    def test_no_venv_returns_base_env(self, tmp_path: Path) -> None:
        """No venv → returns unmodified os.environ copy."""
        env = build_project_env(str(tmp_path))
        assert env.get("VIRTUAL_ENV") == os.environ.get("VIRTUAL_ENV")
        assert env["PATH"] == os.environ["PATH"]

    def test_returns_copy_not_reference(self, tmp_path: Path) -> None:
        """Result is a copy, not a reference to os.environ."""
        env = build_project_env(str(tmp_path))
        env["_TEST_SENTINEL"] = "should_not_leak"
        assert "_TEST_SENTINEL" not in os.environ

    def test_worktree_resolves_main_repo_venv(self, tmp_path: Path) -> None:
        """Full integration: worktree resolves main repo's venv."""
        # Set up main repo with venv
        main_repo = tmp_path / "main-repo"
        main_repo.mkdir()
        (main_repo / ".git").mkdir()
        (main_repo / ".git" / "worktrees").mkdir(parents=True)
        (main_repo / ".git" / "worktrees" / "task-abc").mkdir()
        venv = main_repo / "backend" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        # Set up worktree
        worktree = tmp_path / "worktree-abc"
        worktree.mkdir()
        gitdir = str(main_repo / ".git" / "worktrees" / "task-abc")
        (worktree / ".git").write_text(f"gitdir: {gitdir}\n")

        env = build_project_env(str(worktree))
        assert env["VIRTUAL_ENV"] == str(main_repo / "backend" / ".venv")
        assert str(venv) in env["PATH"]

    def test_preserves_existing_path_entries(self, tmp_path: Path) -> None:
        """Existing PATH entries are preserved after the venv bin."""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        original_path = os.environ.get("PATH", "")
        env = build_project_env(str(tmp_path))
        # PATH should be: venv_bin:original_path
        assert env["PATH"] == f"{venv}:{original_path}"

    def test_path_type_input(self, tmp_path: Path) -> None:
        """Accepts Path objects as well as strings."""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        env = build_project_env(tmp_path)
        assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")

    def test_dot_working_dir(self) -> None:
        """'.' as working_dir resolves to current directory."""
        # Should not crash — returns env based on current dir
        env = build_project_env(".")
        assert "PATH" in env

    def test_nonexistent_working_dir(self, tmp_path: Path) -> None:
        """Nonexistent working dir → returns base env (no crash)."""
        env = build_project_env(str(tmp_path / "nonexistent"))
        assert "PATH" in env

    def test_symlinked_venv_not_followed_into_worktree(self, tmp_path: Path) -> None:
        """Worktree shouldn't need a symlinked .venv — main repo's is found via .git file."""
        # Main repo with venv
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        (main_repo / ".git").mkdir()
        (main_repo / ".git" / "worktrees" / "wt1").mkdir(parents=True)
        venv = main_repo / "backend" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        # Worktree WITHOUT any .venv or symlink
        worktree = tmp_path / "wt1"
        worktree.mkdir()
        gitdir = str(main_repo / ".git" / "worktrees" / "wt1")
        (worktree / ".git").write_text(f"gitdir: {gitdir}\n")

        env = build_project_env(str(worktree))
        # Should resolve main repo's venv, NOT require a symlink
        assert env["VIRTUAL_ENV"] == str(main_repo / "backend" / ".venv")


class TestBuildVenvEnvOverlay:
    """Tests for build_venv_env_overlay() — SDK merge-compatible delta."""

    def test_returns_only_venv_keys(self, tmp_path: Path) -> None:
        """Overlay contains venv keys plus shared command-guard env when available."""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        overlay = build_venv_env_overlay(str(tmp_path))
        assert {"VIRTUAL_ENV", "PATH", "PYTHONHOME"} <= set(overlay.keys())
        assert set(overlay.keys()) <= {
            "VIRTUAL_ENV",
            "PATH",
            "PYTHONHOME",
            "SUMMITFLOW_SCRIPTS_DIR",
            "SF_COMMAND_GUARD_BIN",
            "SF_COMMAND_GUARD_WORDS",
            "BASH_ENV",
            "SF_COMMAND_GUARD_PREV_BASH_ENV",
        }

    def test_virtual_env_set(self, tmp_path: Path) -> None:
        """VIRTUAL_ENV points to the resolved venv."""
        venv = tmp_path / "backend" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        overlay = build_venv_env_overlay(str(tmp_path))
        assert overlay["VIRTUAL_ENV"] == str(tmp_path / "backend" / ".venv")

    def test_path_prepended(self, tmp_path: Path) -> None:
        """PATH starts with venv bin dir."""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        overlay = build_venv_env_overlay(str(tmp_path))
        assert overlay["PATH"].startswith(str(venv))

    def test_pythonhome_is_empty_string(self, tmp_path: Path) -> None:
        """PYTHONHOME is set to empty string (overrides os.environ in SDK merge)."""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        overlay = build_venv_env_overlay(str(tmp_path))
        assert overlay["PYTHONHOME"] == ""

    def test_pythonhome_override_in_sdk_merge(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Simulates SDK merge: PYTHONHOME from os.environ is overridden to empty."""
        monkeypatch.setenv("PYTHONHOME", "/dangerous/python/home")
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        overlay = build_venv_env_overlay(str(tmp_path))

        # Simulate SDK merge: {**os.environ, **overlay}
        merged = {**os.environ, **overlay}
        assert merged["PYTHONHOME"] == ""  # Overridden, not the dangerous value
        assert merged["VIRTUAL_ENV"] == str(tmp_path / ".venv")

    def test_no_venv_returns_empty_dict(self, tmp_path: Path) -> None:
        """No venv found → returns command-guard env only, never venv keys."""
        overlay = build_venv_env_overlay(str(tmp_path))
        assert "VIRTUAL_ENV" not in overlay
        assert "PYTHONHOME" not in overlay
        assert "PATH" not in overlay

    def test_worktree_resolves_main_repo(self, tmp_path: Path) -> None:
        """Worktree resolves main repo's venv in overlay."""
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        (main_repo / ".git").mkdir()
        (main_repo / ".git" / "worktrees" / "wt1").mkdir(parents=True)
        venv = main_repo / "backend" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        worktree = tmp_path / "wt1"
        worktree.mkdir()
        gitdir = str(main_repo / ".git" / "worktrees" / "wt1")
        (worktree / ".git").write_text(f"gitdir: {gitdir}\n")

        overlay = build_venv_env_overlay(str(worktree))
        assert overlay["VIRTUAL_ENV"] == str(main_repo / "backend" / ".venv")

    def test_sdk_merge_produces_correct_env(self, tmp_path: Path) -> None:
        """Full simulation: overlay + SDK merge = correct subprocess env."""
        venv = tmp_path / "backend" / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/usr/bin/env python3\n")

        overlay = build_venv_env_overlay(str(tmp_path))

        # Simulate exactly what Claude SDK does:
        # process_env = {**os.environ, **options.env, "CLAUDE_CODE_ENTRYPOINT": "sdk-py"}
        process_env = {**os.environ, **overlay, "CLAUDE_CODE_ENTRYPOINT": "sdk-py"}

        assert process_env["VIRTUAL_ENV"] == str(tmp_path / "backend" / ".venv")
        assert process_env["PATH"].startswith(str(venv))
        assert process_env["PYTHONHOME"] == ""
        assert process_env["CLAUDE_CODE_ENTRYPOINT"] == "sdk-py"
        # Original PATH entries still present
        assert os.environ.get("PATH", "") in process_env["PATH"]

    def test_build_project_env_merges_shared_command_guard(self, tmp_path: Path) -> None:
        """Project env should carry shared guard vars even without a venv."""
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "app.services.tools.project_env.build_command_guard_env_overlay",
                lambda: {
                    "BASH_ENV": "/tmp/bash-command-guard.sh",
                    "SF_COMMAND_GUARD_BIN": "/tmp/command-guard",
                    "SF_COMMAND_GUARD_WORDS": "git env",
                },
            )
            env = build_project_env(str(tmp_path))

        assert env["BASH_ENV"] == "/tmp/bash-command-guard.sh"
        assert env["SF_COMMAND_GUARD_BIN"] == "/tmp/command-guard"
        assert env["SF_COMMAND_GUARD_WORDS"] == "git env"
