"""Tests for prompt revision API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.prompt import Prompt, PromptRevision


def _make_revision(**overrides):
    revision = PromptRevision(
        prompt_id=12,
        prompt_slug="persona-heartbeat-instructions",
        prompt_name="Persona Heartbeat Instructions",
        action="update",
        content="Heartbeat text",
        description="Persona guidance",
        is_global=False,
        enabled=True,
        exclude_agents=[],
        content_hash="abcd1234",
        changed_by="persona",
        change_reason="test update",
    )
    revision.id = "rev-1"
    revision.created_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(revision, key, value)
    return revision


def _make_prompt(**overrides):
    prompt = Prompt(
        slug="persona-heartbeat-instructions",
        name="Persona Heartbeat Instructions",
        content="Heartbeat text",
        description="Persona guidance",
        is_global=False,
        enabled=True,
        exclude_agents=[],
    )
    prompt.id = 12
    prompt.created_at = datetime.now(UTC)
    prompt.updated_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(prompt, key, value)
    return prompt


class TestPromptRevisionEndpoints:
    @pytest.mark.asyncio
    async def test_list_prompt_revisions_returns_history(self, api_client):
        with patch(
            "app.api.prompts.list_prompt_revisions",
            new=AsyncMock(return_value=[_make_revision()]),
        ):
            response = api_client.get("/api/prompts/persona-heartbeat-instructions/revisions")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["revisions"][0]["id"] == "rev-1"
        assert data["revisions"][0]["action"] == "update"

    @pytest.mark.asyncio
    async def test_restore_prompt_revision_returns_restored_prompt(self, api_client):
        with (
            patch(
                "app.api.prompts.get_prompt_revision",
                new=AsyncMock(return_value=_make_revision()),
            ),
            patch(
                "app.api.prompts.restore_prompt_revision",
                new=AsyncMock(return_value=_make_prompt(content="Restored heartbeat text")),
            ),
        ):
            response = api_client.post(
                "/api/prompts/persona-heartbeat-instructions/revisions/rev-1/restore",
                json={"change_reason": "Rollback candidate"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == "persona-heartbeat-instructions"
        assert data["content"] == "Restored heartbeat text"

    @pytest.mark.asyncio
    async def test_restore_prompt_revision_returns_404_when_revision_missing(self, api_client):
        with patch(
            "app.api.prompts.get_prompt_revision",
            new=AsyncMock(return_value=None),
        ):
            response = api_client.post(
                "/api/prompts/persona-heartbeat-instructions/revisions/missing/restore",
                json={},
            )

        assert response.status_code == 404
