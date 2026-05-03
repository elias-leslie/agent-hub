"""Tests for scratch-context direct tool behavior."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.tools.direct_executor import DirectToolExecutor
from app.services.tools.scratch_context import ScratchContextStore


def _artifact_id(output: str) -> str:
    match = re.search(r"artifact_id: (scratch_[a-f0-9]+)", output)
    assert match is not None
    return match.group(1)


def test_store_and_search_artifact(tmp_path: Path) -> None:
    store = ScratchContextStore(tmp_path)
    summary = store.store_text(
        "alpha\nbefore\nneedle exact hit\nafter\nomega\n",
        source="test",
        label="unit artifact",
        project_id="agent-hub",
        session_id="session-1",
        agent_slug="coder",
        working_dir=tmp_path,
    )

    result = store.search(
        query="needle exact",
        artifact_id=summary.artifact_id,
        project_id="agent-hub",
        session_id="session-1",
        limit=3,
        context_lines=1,
    )

    assert "SCRATCH_SEARCH" in result
    assert summary.artifact_id in result
    assert "2: before" in result
    assert "3: needle exact hit" in result


def test_search_requires_query(tmp_path: Path) -> None:
    store = ScratchContextStore(tmp_path)

    result = store.search(
        query=" ",
        artifact_id=None,
        project_id="agent-hub",
        session_id="session-1",
    )

    assert result == "Error: query is required for scratch search."


def test_search_missing_artifact(tmp_path: Path) -> None:
    store = ScratchContextStore(tmp_path)

    result = store.search(
        query="needle",
        artifact_id="scratch_missing",
        project_id="agent-hub",
        session_id="session-1",
    )

    assert result == "Error: Scratch artifact not found: scratch_missing"


@pytest.mark.asyncio
async def test_bash_small_output_passthrough(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_HUB_SCRATCH_CONTEXT_DIR", str(tmp_path / "scratch"))
    executor = DirectToolExecutor(str(tmp_path), project_id="agent-hub", session_id="session-1")

    result = await executor.bash("echo small-output")

    assert result.strip() == "small-output"
    assert "SCRATCH_ARTIFACT_INDEXED" not in result


@pytest.mark.asyncio
async def test_bash_large_output_indexes_and_searches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_HUB_SCRATCH_CONTEXT_DIR", str(tmp_path / "scratch"))
    executor = DirectToolExecutor(str(tmp_path), project_id="agent-hub", session_id="session-1")
    command = "python3 - <<'PY'\nfor i in range(12050):\n    print(f'line {i} NEEDLE_{i}')\nPY"

    result = await executor.bash(command)
    artifact_id = _artifact_id(result)

    assert "SCRATCH_ARTIFACT_INDEXED" in result
    assert "stored:" in result
    assert "search_scratch_context" in result
    assert "NEEDLE_12049" in result

    search = await executor.search_scratch_context("NEEDLE_7777", artifact_id=artifact_id, context_lines=1)

    assert "SCRATCH_SEARCH" in search
    assert artifact_id in search
    assert "NEEDLE_7777" in search
    assert "line 7777" in search


@pytest.mark.asyncio
async def test_dispatch_search_scratch_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_HUB_SCRATCH_CONTEXT_DIR", str(tmp_path / "scratch"))
    executor = DirectToolExecutor(str(tmp_path), project_id="agent-hub", session_id="session-1")
    store = ScratchContextStore(tmp_path / "scratch")
    summary = store.store_text(
        "alpha\nrare dispatch term\nomega\n",
        source="test",
        label="dispatch artifact",
        project_id="agent-hub",
        session_id="session-1",
        agent_slug=None,
        working_dir=tmp_path,
    )

    result = await executor.dispatch(
        "search_scratch_context",
        {"query": "rare dispatch", "artifact_id": summary.artifact_id, "bogus": "ignored"},
    )

    assert "rare dispatch term" in result


@pytest.mark.asyncio
async def test_batch_execute_mixes_inline_and_indexed_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_HUB_SCRATCH_CONTEXT_DIR", str(tmp_path / "scratch"))
    executor = DirectToolExecutor(str(tmp_path), project_id="agent-hub", session_id="session-1")
    large_command = "python3 - <<'PY'\nfor i in range(1600):\n    print(f'batch line {i} BATCH_NEEDLE_{i}')\nPY"

    result = await executor.batch_execute(["echo inline-small", large_command])
    artifact_id = _artifact_id(result)

    assert "BATCH_EXECUTE[requested=2|ran=2|indexed=1" in result
    assert "inline-small" in result
    assert "SCRATCH_ARTIFACT_INDEXED" in result
    assert "saved_tokens~=" in result

    search = await executor.search_scratch_context("BATCH_NEEDLE_1200", artifact_id=artifact_id)

    assert "BATCH_NEEDLE_1200" in search


@pytest.mark.asyncio
async def test_batch_execute_rejects_too_many_commands(tmp_path: Path) -> None:
    executor = DirectToolExecutor(str(tmp_path))

    result = await executor.batch_execute(["echo x"] * 9)

    assert result == "Error: batch_execute accepts at most 8 commands."
