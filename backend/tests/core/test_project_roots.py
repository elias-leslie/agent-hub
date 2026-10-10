"""Tests for canonical project root resolution helpers."""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import project_roots
from app.core.project_roots import (
    aresolve_project_root,
    clear_project_root_cache,
    resolve_project_root,
    resolve_summitflow_scripts_dir,
)


@pytest.fixture(autouse=True)
def _no_inherited_root_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    # The st launcher exports SUMMITFLOW_ROOT to the processes it runs.
    for key in ("SUMMITFLOW_ROOT", "A_TERM_ROOT"):
        monkeypatch.delenv(key, raising=False)


def test_resolve_project_root_prefers_env_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUMMITFLOW_ROOT", str(tmp_path))
    clear_project_root_cache()

    resolved = resolve_project_root("summitflow")

    assert resolved == tmp_path.resolve()


def test_resolve_summitflow_scripts_dir_uses_rebuild_path(tmp_path: Path, monkeypatch) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "rebuild.sh").write_text("#!/usr/bin/env bash\n")
    monkeypatch.delenv("SUMMITFLOW_SCRIPTS_DIR", raising=False)
    monkeypatch.delenv("SUMMITFLOW_ROOT", raising=False)
    clear_project_root_cache()
    resolve_summitflow_scripts_dir.cache_clear()

    with (
        patch("app.core.project_roots.resolve_project_root", return_value=None),
        patch("app.core.project_roots.shutil.which", return_value=str(scripts_dir / "rebuild.sh")),
    ):
        resolved = resolve_summitflow_scripts_dir()

    assert resolved == scripts_dir.resolve()


def test_resolve_project_root_uses_st_projects_root(tmp_path: Path) -> None:
    clear_project_root_cache()

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
    clear_project_root_cache()
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
    clear_project_root_cache()
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


def test_resolve_project_root_rejects_ids_that_escape_or_inject(tmp_path: Path) -> None:
    clear_project_root_cache()
    workspace = tmp_path / "projects"
    workspace.mkdir()
    (tmp_path / "outside").mkdir()

    with (
        patch("app.core.project_roots._CANONICAL_WORKSPACE_ROOT", workspace),
        patch("app.core.project_roots.shutil.which", return_value="/usr/bin/st"),
        patch("app.core.project_roots.run_process") as run_process,
    ):
        for project_id in ("../outside", "--help", "a/b", "..", "", "x" * 200):
            assert resolve_project_root(project_id) is None
    run_process.assert_not_called()


@pytest.mark.asyncio
async def test_aresolve_project_root_runs_cold_st_lookup_off_the_event_loop(tmp_path: Path) -> None:
    clear_project_root_cache()
    loop_thread = threading.get_ident()
    calling_threads: list[int] = []

    def fake_run_process(*_args: object, **_kwargs: object) -> SimpleNamespace:
        calling_threads.append(threading.get_ident())
        return SimpleNamespace(returncode=0, stdout=str(tmp_path), stderr="")

    with (
        patch("app.core.project_roots.shutil.which", return_value="/usr/bin/st"),
        patch("app.core.project_roots.run_process", side_effect=fake_run_process),
    ):
        assert await aresolve_project_root("a-term") == tmp_path.resolve()
        # Warm lookups are served from the memo without a thread hop or subprocess.
        with patch("app.core.project_roots.asyncio.to_thread") as to_thread:
            assert await aresolve_project_root("a-term") == tmp_path.resolve()
        to_thread.assert_not_called()

    assert len(calling_threads) == 1
    assert calling_threads[0] != loop_thread


@pytest.mark.asyncio
async def test_aresolve_project_root_rejects_invalid_ids_without_lookup() -> None:
    clear_project_root_cache()
    with patch("app.core.project_roots.asyncio.to_thread") as to_thread:
        assert await aresolve_project_root("../outside") is None
    to_thread.assert_not_called()


class _FakeProcess:
    def __init__(self, *, stdout: bytes = b"", returncode: int = 0, hang: bool = False) -> None:
        self._stdout = stdout
        self.returncode = returncode
        self._hang = hang
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang and not self.killed:
            await asyncio.sleep(3600)
        return self._stdout, b"boom"

    def kill(self) -> None:
        self.killed = True


def _registry_payload(**roots: str) -> bytes:
    return json.dumps([{"id": key, "root_path": value} for key, value in roots.items()]).encode()


@pytest.fixture
def fresh_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_roots, "_registry_roots", None)
    monkeypatch.setattr(project_roots, "_registry_loaded_at", 0.0)
    monkeypatch.setattr(project_roots, "_last_good_roots", None)
    monkeypatch.setattr(project_roots, "_registry_retry_after", 0.0)
    monkeypatch.setattr(project_roots, "_REGISTRY_TIMEOUT_SECONDS", 0.01)


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_registry")
async def test_registry_refresh_timeout_serves_last_good_registry() -> None:
    good = _FakeProcess(stdout=_registry_payload(**{"agent-hub": "/srv/a"}))
    hung = _FakeProcess(hang=True)
    with patch.object(project_roots, "create_process", AsyncMock(side_effect=[good, hung])) as spawn:
        assert await project_roots.get_registered_project_roots() == {"agent-hub": "/srv/a"}
        assert await project_roots.get_registered_project_roots(refresh=True) == {"agent-hub": "/srv/a"}
        assert hung.killed
        # Within the retry window the stale registry is served without re-spawning st.
        assert await project_roots.get_registered_project_roots(refresh=True) == {"agent-hub": "/srv/a"}
    assert spawn.await_count == 2


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_registry")
async def test_registry_failure_after_invalidate_serves_last_good_then_recovers() -> None:
    good = _FakeProcess(stdout=_registry_payload(**{"agent-hub": "/srv/a"}))
    failed = _FakeProcess(returncode=1)
    newer = _FakeProcess(stdout=_registry_payload(**{"agent-hub": "/srv/a", "neri": "/srv/n"}))
    with patch.object(project_roots, "create_process", AsyncMock(side_effect=[good, failed, newer])):
        await project_roots.get_registered_project_roots()
        project_roots.invalidate_registered_project_roots()
        assert await project_roots.get_registered_project_roots() == {"agent-hub": "/srv/a"}
        project_roots.invalidate_registered_project_roots()  # also clears the retry window
        assert await project_roots.get_registered_project_roots() == {
            "agent-hub": "/srv/a",
            "neri": "/srv/n",
        }


@pytest.mark.asyncio
@pytest.mark.usefixtures("fresh_registry")
async def test_registry_timeout_without_cache_raises() -> None:
    hung = _FakeProcess(hang=True)
    with (
        patch.object(project_roots, "create_process", AsyncMock(return_value=hung)),
        pytest.raises(project_roots.ProjectRegistryUnavailable, match="timed out"),
    ):
        await project_roots.get_registered_project_roots()
    assert hung.killed
