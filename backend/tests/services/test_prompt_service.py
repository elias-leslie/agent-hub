"""Tests for prompt revision tracking and restore flow."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.models.prompt import Prompt, PromptRevision
from app.services.prompt_service import (
    create_prompt,
    get_prompt_content,
    get_prompt_revision,
    require_prompt_content,
    resolve_prompt_revision_id_prefix,
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

    @pytest.mark.asyncio
    async def test_get_prompt_revision_resolves_short_prefix_before_lookup(self) -> None:
        db = AsyncMock()
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = {"id": "full-revision-id"}
        db.execute.return_value = mock_result

        with patch(
            "app.services.prompt_service.resolve_prompt_revision_id_prefix",
            new=AsyncMock(return_value="12345678-1234-1234-1234-123456789abc"),
        ) as mock_resolve:
            revision = await get_prompt_revision(
                db,
                "persona-heartbeat-instructions",
                "12345678",
            )

        assert revision == {"id": "full-revision-id"}
        mock_resolve.assert_awaited_once_with(
            db,
            "persona-heartbeat-instructions",
            "12345678",
        )
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_prompt_revision_id_prefix_rejects_ambiguous_matches(self) -> None:
        db = AsyncMock()
        mock_result = Mock()
        mock_scalars = Mock()
        mock_scalars.all.return_value = [
            "12345678-1234-1234-1234-123456789abc",
            "12345678-9999-9999-9999-999999999999",
        ]
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Ambiguous prompt revision prefix"):
            await resolve_prompt_revision_id_prefix(
                db,
                "persona-heartbeat-instructions",
                "12345678",
            )


class TestPromptRuntimeReads:
    @pytest.mark.asyncio
    async def test_get_prompt_content_strips_transport_headers(self) -> None:
        prompt = _make_prompt(
            content=(
                "PROMPT:persona-heartbeat-instructions|Persona Heartbeat Instructions|N|181L\n"
                "PROMPT:persona-heartbeat-instructions|Persona Heartbeat Instructions|N|177L\n"
                "# Heartbeat Contract\n\n## Goal\nShip fixes."
            )
        )

        @asynccontextmanager
        async def _session():
            yield object()

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.services.prompt_service.get_prompt_by_slug",
                new=AsyncMock(return_value=prompt),
            ),
        ):
            content = await get_prompt_content("persona-heartbeat-instructions", "fallback")

        assert content.startswith("# Heartbeat Contract")
        assert "PROMPT:" not in content

    @pytest.mark.asyncio
    async def test_require_prompt_content_strips_transport_headers(self) -> None:
        prompt = _make_prompt(
            content=(
                "PROMPT:persona-heartbeat-instructions|Persona Heartbeat Instructions|N|181L\n"
                "# Heartbeat Contract\nShip fixes."
            )
        )

        @asynccontextmanager
        async def _session():
            yield object()

        with (
            patch("app.db.async_session", _session),
            patch(
                "app.services.prompt_service.get_prompt_by_slug",
                new=AsyncMock(return_value=prompt),
            ),
        ):
            content = await require_prompt_content("persona-heartbeat-instructions")

        assert content == "# Heartbeat Contract\nShip fixes."
