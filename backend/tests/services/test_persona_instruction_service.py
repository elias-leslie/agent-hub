"""Tests for prompt-backed Jenny heartbeat instruction updates."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.prompt import Prompt
from app.services.persona_instruction_service import set_persona_heartbeat_instructions
from tests.conftest import create_mock_db_session


class TestPersonaInstructionService:
    @pytest.mark.asyncio
    async def test_set_persona_heartbeat_instructions_syncs_prompt_documents(self) -> None:
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
        agent = SimpleNamespace(id=27, slug="persona")

        with (
            patch(
                "app.services.persona_instruction_service.get_prompt_by_slug",
                new=AsyncMock(side_effect=[prompt, None, None]),
            ),
            patch(
                "app.services.persona_instruction_service._get_persona_agent",
                new=AsyncMock(return_value=agent),
            ),
            patch(
                "app.services.persona_instruction_service.sync_persona_document_prompts",
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
            personality="",
            user_context="",
            heartbeat_instructions="New heartbeat text",
            changed_by="persona",
            change_reason="benchmark promote",
        )
