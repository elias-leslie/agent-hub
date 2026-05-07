from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.tools.direct_executor_core import DirectToolExecutor


@pytest.mark.asyncio
async def test_direct_executor_reads_cross_project_file_when_target_project_allows_read(
    tmp_path: Path,
) -> None:
    agent_hub = tmp_path / "agent-hub"
    summitflow = tmp_path / "summitflow"
    agent_hub.mkdir()
    summitflow.mkdir()
    target = summitflow / "backend" / "cli" / "commands" / "prompt.py"
    target.parent.mkdir(parents=True)
    target.write_text("prompt = 'ok'\n", encoding="utf-8")

    with (
        patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"agent-hub": str(agent_hub), "summitflow": str(summitflow)},
        ),
        patch(
            "app.services.tools._cross_project_hook._resolve_tier",
            new=AsyncMock(return_value="read"),
        ),
    ):
        executor = DirectToolExecutor(working_dir=str(agent_hub), project_id="agent-hub")
        result = await executor.read_file(str(target), offset=0, limit=10)

    assert not result.startswith("Error:")
    assert "prompt = 'ok'" in result


@pytest.mark.asyncio
async def test_direct_executor_blocks_cross_project_write_when_target_project_is_read_only(
    tmp_path: Path,
) -> None:
    agent_hub = tmp_path / "agent-hub"
    summitflow = tmp_path / "summitflow"
    agent_hub.mkdir()
    summitflow.mkdir()
    target = summitflow / "backend" / "cli" / "commands" / "prompt.py"
    target.parent.mkdir(parents=True)

    with (
        patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"agent-hub": str(agent_hub), "summitflow": str(summitflow)},
        ),
        patch(
            "app.services.tools._cross_project_hook._resolve_tier",
            new=AsyncMock(return_value="read"),
        ),
    ):
        executor = DirectToolExecutor(working_dir=str(agent_hub), project_id="agent-hub")
        result = await executor.write_file(str(target), "prompt = 'bad'\n")

    assert result == "Error: Project permission denied for summitflow: read-only"
    assert not target.exists()


@pytest.mark.asyncio
async def test_direct_executor_writes_cross_project_file_when_target_project_allows_write(
    tmp_path: Path,
) -> None:
    agent_hub = tmp_path / "agent-hub"
    summitflow = tmp_path / "summitflow"
    agent_hub.mkdir()
    summitflow.mkdir()
    target = summitflow / "backend" / "cli" / "commands" / "prompt.py"
    target.parent.mkdir(parents=True)

    with (
        patch(
            "app.services.tools.direct_executor_core.KNOWN_ROOTS",
            {"agent-hub": str(agent_hub), "summitflow": str(summitflow)},
        ),
        patch(
            "app.services.tools._cross_project_hook._resolve_tier",
            new=AsyncMock(return_value="full"),
        ),
    ):
        executor = DirectToolExecutor(working_dir=str(agent_hub), project_id="agent-hub")
        result = await executor.write_file(str(target), "prompt = 'ok'\n")

    assert result.startswith("Successfully wrote ")
    assert target.read_text(encoding="utf-8") == "prompt = 'ok'\n"
