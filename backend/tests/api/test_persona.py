"""Tests for persona API endpoints (app/api/persona.py)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.persona import Persona
from app.models.persona_journal import PersonaJournal


def _make_persona(**overrides) -> MagicMock:
    """Create a mock Persona with sensible defaults."""
    defaults = {
        "id": 1,
        "agent_id": 10,
        "name": "Jenny",
        "personality": "I'm a helpful AI.",
        "heartbeat_instructions": "Check health.",
        "user_context": "User likes brevity.",
        "tools_guidance": "Use tools wisely.",
        "voice_id": "en-US-AriaNeural",
        "voice_enabled": False,
        "heartbeat_interval_minutes": 60,
        "avatar_url": None,
        "greeting": "Hey!",
        "onboarding_complete": True,
        "version": 2,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Persona)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_journal(**overrides) -> MagicMock:
    """Create a mock PersonaJournal for testing."""
    defaults = {
        "id": 1,
        "persona_id": 1,
        "entry_date": date.today(),
        "content": "Test journal entry.",
        "entry_type": "observation",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    mock = MagicMock(spec=PersonaJournal)
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

    def test_resets_onboarding_flag(self, api_client, mock_db_session):
        persona = _make_persona(onboarding_complete=True, version=3)

        with patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock:
            mock.return_value = persona
            response = api_client.post("/api/persona/reset-onboarding")

        assert response.status_code == 200
        data = response.json()
        assert data["onboarding_complete"] is False
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

    def test_returns_entries_list(self, api_client, mock_db_session):
        persona = _make_persona()
        entry = _make_journal(
            id=5,
            entry_date=date.today(),
            content="Observed something.",
            entry_type="observation",
        )

        # Mock: first execute for get_or_create_persona, second for journal query
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = [entry]
        mock_db_session.execute.side_effect = [mock_result_persona, mock_result_journal]

        response = api_client.get("/api/persona/journal")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["entries"][0]["content"] == "Observed something."
        assert data["entries"][0]["entry_type"] == "observation"

    def test_custom_days_back(self, api_client, mock_db_session):
        persona = _make_persona()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        mock_db_session.execute.side_effect = [mock_result_persona, mock_result_journal]

        response = api_client.get("/api/persona/journal?days_back=90")

        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_empty_journal(self, api_client, mock_db_session):
        persona = _make_persona()
        mock_result_persona = MagicMock()
        mock_result_persona.scalar_one_or_none.return_value = persona
        mock_result_journal = MagicMock()
        mock_result_journal.scalars.return_value.all.return_value = []
        mock_db_session.execute.side_effect = [mock_result_persona, mock_result_journal]

        response = api_client.get("/api/persona/journal")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["entries"] == []
