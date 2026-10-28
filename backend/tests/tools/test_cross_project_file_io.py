from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.tools.direct_executor_core import DirectToolExecutor


@pytest.mark.asyncio
async def test_direct_executor_reads_a_file_in_another_registered_project(
    tmp_path: Path,
) -> None:
    agent_hub = tmp_path / "agent-hub"
    summitflow = tmp_path / "summitflow"
    agent_hub.mkdir()
    summitflow.mkdir()
    target = summitflow / "backend" / "cli" / "commands" / "prompt.py"
    target.parent.mkdir(parents=True)
    target.write_text("prompt = 'ok'\n", encoding="utf-8")

    with patch(
        "app.services.tools.direct_executor_core.KNOWN_ROOTS",
        {"agent-hub": str(agent_hub), "summitflow": str(summitflow)},
    ):
        executor = DirectToolExecutor(working_dir=str(agent_hub), project_id="agent-hub")
        result = await executor.read_file(str(target), offset=0, limit=10)

    assert not result.startswith("Error:")
    assert "prompt = 'ok'" in result


@pytest.mark.asyncio
async def test_direct_executor_writes_a_file_in_another_registered_project(
    tmp_path: Path,
) -> None:
    agent_hub = tmp_path / "agent-hub"
    summitflow = tmp_path / "summitflow"
    agent_hub.mkdir()
    summitflow.mkdir()
    target = summitflow / "backend" / "cli" / "commands" / "prompt.py"
    target.parent.mkdir(parents=True)

    with patch(
        "app.services.tools.direct_executor_core.KNOWN_ROOTS",
        {"agent-hub": str(agent_hub), "summitflow": str(summitflow)},
    ):
        executor = DirectToolExecutor(working_dir=str(agent_hub), project_id="agent-hub")
        result = await executor.write_file(str(target), "prompt = 'ok'\n")

    assert result.startswith("Successfully wrote ")
    assert target.read_text(encoding="utf-8") == "prompt = 'ok'\n"
