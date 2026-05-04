"""Tests for canonical project root resolution helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.project_roots import resolve_project_root, resolve_summitflow_scripts_dir


def test_resolve_project_root_prefers_env_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUMMITFLOW_ROOT", str(tmp_path))
    resolve_project_root.cache_clear()

    resolved = resolve_project_root("summitflow")

    assert resolved == tmp_path.resolve()


def test_resolve_summitflow_scripts_dir_uses_rebuild_path(tmp_path: Path, monkeypatch) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "rebuild.sh").write_text("#!/usr/bin/env bash\n")
    monkeypatch.delenv("SUMMITFLOW_SCRIPTS_DIR", raising=False)
    monkeypatch.delenv("SUMMITFLOW_ROOT", raising=False)
    resolve_project_root.cache_clear()
    resolve_summitflow_scripts_dir.cache_clear()

    with (
        patch("app.core.project_roots.resolve_project_root", return_value=None),
        patch("app.core.project_roots.shutil.which", return_value=str(scripts_dir / "rebuild.sh")),
    ):
        resolved = resolve_summitflow_scripts_dir()

    assert resolved == scripts_dir.resolve()


def test_resolve_project_root_uses_st_projects_root(tmp_path: Path) -> None:
    resolve_project_root.cache_clear()

    with (
        patch("app.core.project_roots.shutil.which", return_value="/usr/bin/st"),
        patch(
            "app.core.project_roots.run_process",
            return_value=SimpleNamespace(returncode=0, stdout=str(tmp_path), stderr=""),
        ),
        patch("pathlib.Path.exists", return_value=True),
    ):
        resolved = resolve_project_root("a-term")

    assert resolved == tmp_path.resolve()


def test_resolve_project_root_falls_back_when_st_times_out(tmp_path: Path) -> None:
    resolve_project_root.cache_clear()
    candidate = tmp_path / "summitflow"
    candidate.mkdir()

    with (
        patch("app.core.project_roots._CANONICAL_WORKSPACE_ROOT", tmp_path),
        patch("app.core.project_roots.shutil.which", return_value="/usr/bin/st"),
        patch(
            "app.core.project_roots.run_process",
            side_effect=subprocess.TimeoutExpired(["st", "projects", "root", "summitflow"], timeout=5),
        ),
    ):
        resolved = resolve_project_root("summitflow")

    assert resolved == candidate.resolve()


def test_resolve_project_root_uses_manifest_aliases_when_workspace_folder_differs(
    tmp_path: Path,
) -> None:
    resolve_project_root.cache_clear()
    repo_root = tmp_path / "a-term"
    repo_root.mkdir()
    (repo_root / "project.identity.json").write_text(
        json.dumps(
            {
                "project": {
                    "id": "a-term",
                    "repo_name": "a-term",
                    "legacy_ids": ["aterm", "terminal"],
                    "repo_aliases": ["aterm", "terminal"],
                    "display_name": "A-Term",
                }
            }
        )
    )

    with (
        patch("app.core.project_roots._CANONICAL_WORKSPACE_ROOT", tmp_path),
        patch("app.core.project_roots.shutil.which", return_value=None),
    ):
        resolved = resolve_project_root("a-term")

    assert resolved == repo_root.resolve()
