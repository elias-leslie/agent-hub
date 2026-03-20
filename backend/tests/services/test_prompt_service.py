"""Tests for prompt revision tracking and restore flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models.prompt import Prompt, PromptRevision
from app.services.prompt_service import (
    create_prompt,
    restore_prompt_revision,
    update_prompt,
)
from tests.conftest import create_mock_db_session


def _make_prompt(**overrides: object) -> Prompt:
    prompt = Prompt(
        slug="persona-heartbeat-instructions",
        name="Persona Heartbeat Instructions",
        content="Initial heartbeat instructions",
        description="Persona guidance",
        is_global=False,
        enabled=True,
        exclude_agents=[],
    )
    prompt.id = 12
    for key, value in overrides.items():
        setattr(prompt, key, value)
    return prompt


class TestPromptServiceRevisions:
    @pytest.mark.asyncio
    async def test_create_prompt_records_initial_revision(self) -> None:
        db = create_mock_db_session()

        prompt = await create_prompt(
            db,
            slug="test-prompt",
            name="Test Prompt",
            content="hello",
            description="desc",
            changed_by="pytest",
            change_reason="create test",
        )

        revision = db.add.call_args_list[1].args[0]
        assert isinstance(prompt, Prompt)
        assert isinstance(revision, PromptRevision)
        assert revision.action == "create"
        assert revision.prompt_slug == "test-prompt"
        assert revision.changed_by == "pytest"
        assert revision.change_reason == "create test"

    @pytest.mark.asyncio
    async def test_update_prompt_records_revision(self) -> None:
        db = create_mock_db_session()
        prompt = _make_prompt(content="old content")

        with patch(
            "app.services.prompt_service.get_prompt_by_slug",
            new=AsyncMock(return_value=prompt),
        ):
            updated = await update_prompt(
                db,
                "persona-heartbeat-instructions",
                content="new content",
                changed_by="persona",
                change_reason="benchmark tuning",
            )

        revision = db.add.call_args_list[0].args[0]
        assert updated is prompt
        assert prompt.content == "new content"
        assert isinstance(revision, PromptRevision)
        assert revision.action == "update"
        assert revision.content == "new content"
        assert revision.change_reason == "benchmark tuning"

    @pytest.mark.asyncio
    async def test_restore_prompt_revision_restores_snapshot_and_records_restore(self) -> None:
        db = create_mock_db_session()
        prompt = _make_prompt(
            content="current content",
            description="current description",
            enabled=False,
        )
        revision = PromptRevision(
            prompt_slug=prompt.slug,
            prompt_name="Older Prompt Name",
            action="update",
            content="restored content",
            description="restored description",
            is_global=False,
            enabled=True,
            exclude_agents=["reviewer"],
            content_hash="abc123",
        )
        revision.id = "rev-1"

        with (
            patch(
                "app.services.prompt_service.get_prompt_by_slug",
                new=AsyncMock(return_value=prompt),
            ),
            patch(
                "app.services.prompt_service.get_prompt_revision",
                new=AsyncMock(return_value=revision),
            ),
        ):
            restored = await restore_prompt_revision(
                db,
                prompt.slug,
                "rev-1",
                changed_by="pytest",
                change_reason="rollback test",
            )

        recorded_revision = db.add.call_args_list[0].args[0]
        assert restored is prompt
        assert prompt.name == "Older Prompt Name"
        assert prompt.content == "restored content"
        assert prompt.description == "restored description"
        assert prompt.enabled is True
        assert prompt.exclude_agents == ["reviewer"]
        assert isinstance(recorded_revision, PromptRevision)
        assert recorded_revision.action == "restore"
        assert recorded_revision.change_reason == "rollback test"
