"""Tests for persona API endpoints (app/api/persona.py)."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db import get_db
from app.main import app
from app.models.persona import Persona
from app.models.session import Session, SessionEvent, SessionEventType
from tests.conftest import APITestClient


def _make_persona(**overrides) -> MagicMock:
    """Create a mock Persona with sensible defaults."""
    defaults = {
        "id": 1,
        "agent_id": 10,
        "name": "Jenny",
        "personality": "I'm a helpful AI.",
        "heartbeat_instructions": "Check health.",
        "user_context": "User likes brevity.",
        "voice_id": "en-US-AriaNeural",
        "voice_enabled": False,
        "heartbeat_interval_minutes": 60,
        "avatar_url": None,
        "greeting": "Hey!",
        "onboarding_complete": True,
        "onboarding_phase": "complete",
        "session_reset_mode": "off",
        "session_reset_hour": 9,
        "session_reset_idle_minutes": 120,
        "limits": None,
        "version": 2,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Persona)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_journal_memory(**overrides) -> MagicMock:
    """Create a mock Memory object representing a journal entry."""
    now = datetime.now(UTC)
    defaults = {
        "id": "00000000-0000-0000-0000-000000000001",
        "content": "Test journal entry.",
        "memory_type": "journal",
        "scope": "agent:persona",
        "metadata_": {"entry_type": "observation"},
        "valid_at": now,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestGetPersonaEndpoint:
    """Tests for GET /api/persona."""

    def test_returns_persona_response(self, api_client):
        persona = _make_persona()

        with patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock:
            mock.return_value = persona
            response = api_client.get("/api/persona")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["name"] == "Jenny"
        assert data["personality"] == "I'm a helpful AI."
        assert data["version"] == 2
        assert data["agent_slug"] == "persona"
        assert data["onboarding_phase"] == "complete"
        assert data["session_reset_mode"] == "off"
        assert data["session_reset_hour"] == 9
        assert data["session_reset_idle_minutes"] == 120


class TestUpdatePersonaEndpoint:
    """Tests for PUT /api/persona."""

    def test_partial_update(self, api_client, mock_db_session):
        persona = _make_persona(version=2)

        with patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock:
            mock.return_value = persona
            response = api_client.put(
                "/api/persona",
                json={"name": "Aria", "greeting": "Howdy!"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Aria"
        assert data["greeting"] == "Howdy!"
        assert data["version"] == 3  # incremented

    def test_version_increments(self, api_client, mock_db_session):
        persona = _make_persona(version=5)

        with patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock:
            mock.return_value = persona
            response = api_client.put(
                "/api/persona",
                json={"voice_enabled": True},
            )

        assert response.status_code == 200
        assert response.json()["version"] == 6

    def test_no_op_when_empty_update(self, api_client):
        persona = _make_persona(version=2)

        with patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock:
            mock.return_value = persona
            response = api_client.put("/api/persona", json={})

        assert response.status_code == 200
        assert response.json()["version"] == 2  # not incremented


class TestResetOnboardingEndpoint:
    """Tests for POST /api/persona/reset-onboarding."""

    def test_resets_onboarding_flag_and_phase(self, api_client, mock_db_session):
        persona = _make_persona(onboarding_complete=True, onboarding_phase="complete", version=3)

        with patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock:
            mock.return_value = persona
            response = api_client.post("/api/persona/reset-onboarding")

        assert response.status_code == 200
        data = response.json()
        assert data["onboarding_complete"] is False
        assert data["onboarding_phase"] == "not_started"
        assert data["version"] == 4  # incremented


class TestGetPersonalityEndpoint:
    """Tests for GET /api/persona/personality."""

    def test_returns_personality_and_version(self, api_client):
        persona = _make_persona(personality="Creative and bold.", version=7)

        with patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock:
            mock.return_value = persona
            response = api_client.get("/api/persona/personality")

        assert response.status_code == 200
        data = response.json()
        assert data["personality"] == "Creative and bold."
        assert data["version"] == 7

    def test_returns_null_personality_when_not_set(self, api_client):
        persona = _make_persona(personality=None)

        with patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock:
            mock.return_value = persona
            response = api_client.get("/api/persona/personality")

        assert response.status_code == 200
        assert response.json()["personality"] is None


class TestUpdatePersonalityEndpoint:
    """Tests for PUT /api/persona/personality."""

    def test_updates_personality(self, api_client, mock_db_session):
        persona = _make_persona(version=3)

        with patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock:
            mock.return_value = persona
            response = api_client.put(
                "/api/persona/personality",
                json={"personality": "New personality text.", "reason": "Testing"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["personality"] == "New personality text."
        assert data["version"] == 4

    def test_updates_personality_without_reason(self, api_client, mock_db_session):
        persona = _make_persona(version=1)

        with patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock:
            mock.return_value = persona
            response = api_client.put(
                "/api/persona/personality",
                json={"personality": "Updated."},
            )

        assert response.status_code == 200
        assert response.json()["version"] == 2


class TestGetJournalEndpoint:
    """Tests for GET /api/persona/journal."""

    def test_returns_entries_list(self, api_client):
        now = datetime.now(UTC)
        entry = _make_journal_memory(
            content="Observed something.",
            metadata_={"entry_type": "observation"},
            valid_at=now,
            created_at=now,
        )

        mock_repo = AsyncMock()
        mock_repo.list_by_scope_and_tier.return_value = [entry]

        with patch("app.services.memory.repository.get_memory_repository", return_value=mock_repo):
            response = api_client.get("/api/persona/journal")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["entries"][0]["content"] == "Observed something."
        assert data["entries"][0]["entry_type"] == "observation"

    def test_custom_days_back(self, api_client):
        mock_repo = AsyncMock()
        mock_repo.list_by_scope_and_tier.return_value = []

        with patch("app.services.memory.repository.get_memory_repository", return_value=mock_repo):
            response = api_client.get("/api/persona/journal?days_back=90")

        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_empty_journal(self, api_client):
        mock_repo = AsyncMock()
        mock_repo.list_by_scope_and_tier.return_value = []

        with patch("app.services.memory.repository.get_memory_repository", return_value=mock_repo):
            response = api_client.get("/api/persona/journal")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["entries"] == []
