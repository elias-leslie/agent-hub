"""A workflow run's worktree is somewhere the step's file tools can reach.

The tools reach the project's registered root and the step's working directory, and the working directory is accepted
only under a registered root, one of its linked worktrees, or the configured workflow runs root. The worktree the
engine hands out is ``<runs_root>/<run_id>/worktree``, so it has to sit under one of those.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.tools import _executor_roots
from app.services.tools.direct_executor_core import DirectToolExecutor
from app.services.workflow_runs.settings import get_workflow_run_settings
from app.services.workflow_runs.workspace import RunWorkspace


@pytest.fixture
def project_and_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, Path]]:
    project, runs = tmp_path / "project", tmp_path / "state" / "workflow-runs"
    project.mkdir()
    monkeypatch.setenv("AGENT_HUB_WORKFLOW_RUNS_ROOT", str(runs))
    get_workflow_run_settings.cache_clear()
    monkeypatch.setattr(_executor_roots, "_get_known_roots", lambda: {"p": str(project)})
    monkeypatch.setattr(_executor_roots.tempfile, "gettempdir", lambda: str(tmp_path / "unrelated-scratch"))
    yield project, runs
    get_workflow_run_settings.cache_clear()


def run_worktree(run_id: str, lane: str | None = None) -> Path:
    """The worktree a run (or a step's lane) gets, built from the settings the engine reads."""

    root = get_workflow_run_settings().runs_root / run_id
    return RunWorkspace(root, None, None, f"workflow/{run_id[:8]}", lane=lane).worktree


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", [None, "build"])
async def test_run_and_lane_worktrees_are_reachable_by_the_file_tools(project_and_runs, lane) -> None:
    project, _runs = project_and_runs
    worktree = run_worktree("11111111-2222-3333-4444-555555555555", lane)
    worktree.mkdir(parents=True)
    (worktree / "a.txt").write_text("one\n", encoding="utf-8")
    outside = project.parent / "elsewhere"
    outside.mkdir()
    (outside / "secret.txt").write_text("no\n", encoding="utf-8")

    assert _executor_roots.contained_working_dir(str(worktree)) == worktree.resolve()
    with patch("app.services.tools.direct_executor_core.KNOWN_ROOTS", {"p": str(project)}):
        tools = DirectToolExecutor(working_dir=str(worktree), project_id="p")
        assert "one" in await tools.read_file("a.txt")
        assert (await tools.write_file("b.txt", "two\n")).startswith("Successfully wrote ")
        assert (await tools.edit_file("a.txt", old_text="one", new_text="uno")).startswith("Successfully")
        assert (worktree / "b.txt").read_text(encoding="utf-8") == "two\n"
        assert (worktree / "a.txt").read_text(encoding="utf-8") == "uno\n"
        assert (await tools.read_file(str(outside / "secret.txt"))).startswith("Error: Path outside")


def test_a_worktree_outside_every_allowed_root_is_refused(project_and_runs, tmp_path) -> None:
    stray = tmp_path / "stray" / "worktree"
    stray.mkdir(parents=True)
    with pytest.raises(ValueError, match="outside the known project roots"):
        _executor_roots.contained_working_dir(str(stray))
