"""Legacy agent-output memory extraction cannot invoke the curator."""

import pytest
from fastapi import HTTPException

from app.services.memory.agent_output_ingest import (
    extract_agent_output_candidates,
    ingest_agent_output_candidates,
)


@pytest.mark.asyncio
async def test_agent_output_extraction_and_ingestion_are_unavailable() -> None:
    for operation in (
        extract_agent_output_candidates("historical output"),
        ingest_agent_output_candidates("historical output", dry_run=False),
    ):
        with pytest.raises(HTTPException) as raised:
            await operation
        assert raised.value.status_code == 410
