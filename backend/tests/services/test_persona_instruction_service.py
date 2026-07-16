"""Tests for prompt-backed persona heartbeat instruction updates."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.prompt import Prompt
from app.services.persona_instruction_service import set_persona_heartbeat_instructions
from tests.conftest import create_mock_db_session


class TestPersonaInstructionService:
    @pytest.mark.asyncio
    async def test_set_persona_heartbeat_instructions_syncs_instruction_prompt(self) -> None:
        db = create_mock_db_session()
        prompt = Prompt(
            slug="persona-heartbeat-instructions",
            name="Persona Heartbeat Instructions",
            content="Old heartbeat text",
            description="Persona guidance",
            is_global=False,
            enabled=True,
            exclude_agents=[],
        )
        prompt.id = 33
        agent = SimpleNamespace(id=27, slug="persona")

        with (
            patch(
                "app.services.persona_instruction_service.get_prompt_by_slug",
                new=AsyncMock(return_value=prompt),
            ),
            patch(
                "app.services.persona_instruction_service._get_persona_agent",
                new=AsyncMock(return_value=agent),
            ),
            patch(
                "app.services.persona_instruction_service.sync_persona_instruction_prompts",
                new=AsyncMock(),
            ) as mock_sync,
        ):
            old_len, new_len = await set_persona_heartbeat_instructions(
                db,
                "New heartbeat text",
                changed_by="persona",
                change_reason="benchmark promote",
            )

        assert old_len == len("Old heartbeat text")
        assert new_len == len("New heartbeat text")
        mock_sync.assert_awaited_once_with(
            db,
            agent=agent,
            heartbeat_instructions="New heartbeat text",
            changed_by="persona",
            change_reason="benchmark promote",
        )
