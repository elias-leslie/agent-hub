"""Tests for prompt-backed Jenny heartbeat instruction revisions."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models.prompt import Prompt, PromptRevision
from app.services.persona_instruction_service import set_persona_heartbeat_instructions
from tests.conftest import create_mock_db_session


class TestPersonaInstructionService:
    @pytest.mark.asyncio
    async def test_set_persona_heartbeat_instructions_records_revision(self) -> None:
        db = create_mock_db_session()
        prompt = Prompt(
            slug="persona-heartbeat-instructions",
            name="Persona Heartbeat Instructions",
            content="Old heartbeat text",
            description="Jenny guidance",
            is_global=False,
            enabled=True,
            exclude_agents=[],
        )
        prompt.id = 33

        with patch(
            "app.services.persona_instruction_service.get_prompt_by_slug",
            new=AsyncMock(return_value=prompt),
        ):
            old_len, new_len = await set_persona_heartbeat_instructions(
                db,
                "New heartbeat text",
                changed_by="persona",
                change_reason="benchmark promote",
            )

        revision = db.add.call_args_list[0].args[0]
        assert old_len == len("Old heartbeat text")
        assert new_len == len("New heartbeat text")
        assert isinstance(revision, PromptRevision)
        assert revision.action == "update"
        assert revision.changed_by == "persona"
        assert revision.change_reason == "benchmark promote"
