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


# ---------------------------------------------------------------------------
# Activity endpoint — empty-session filter
# ---------------------------------------------------------------------------


def _make_mock_session(session_id: str, **overrides: Any) -> MagicMock:
    """Create a mock Session with sensible defaults for activity tests."""
    now = datetime.now(UTC)
    defaults: dict[str, Any] = {
        "id": session_id,
        "agent_slug": "persona",
        "session_type": "chat",
        "summary_oneliner": None,
        "status": "completed",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Session)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_mock_event(session_id: str, **overrides: Any) -> MagicMock:
    """Create a mock SessionEvent for activity tests."""
    defaults: dict[str, Any] = {
        "session_id": session_id,
        "event_type": SessionEventType.USER_MESSAGE,
        "tool_name": None,
        "content": "Hello persona",
        "turn": 1,
        "sequence": 1,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=SessionEvent)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestBuildSessionQueryHasEventsFilter:
    """Unit test for _build_session_query — verifies the EXISTS(session_events) clause."""

    def test_query_contains_exists_session_events_clause(self) -> None:
        """The generated SQL must include an EXISTS subquery on session_events."""
        from app.api.persona.activity import _build_session_query

        query = _build_session_query(hours=0)
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        # The EXISTS clause references session_events to filter out empty sessions
        assert "session_events" in compiled.lower()
        assert "exists" in compiled.lower()

    def test_query_filters_agent_slug_persona(self) -> None:
        """The generated SQL must filter on agent_slug = 'persona'."""
        from app.api.persona.activity import _build_session_query

        query = _build_session_query(hours=0)
        compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "persona" in compiled.lower()


class TestActivityEndpointEmptySessionFilter:
    """Tests for GET /api/persona/activity — empty-session exclusion.

    The has_events correlated subquery in _build_session_query ensures
    sessions with zero events are excluded from the activity timeline.

    Strategy: patch the three private helpers (_build_session_query,
    _fetch_event_previews, _fetch_message_counts) so the endpoint's
    orchestration layer runs without real SQL, while the db.execute
    calls for count + paginated query are mocked via side_effect.
    """

    @pytest.fixture
    def activity_db(self) -> Generator[AsyncMock]:
        """Provide a mock database session wired into the app for activity tests."""
        mock_session = AsyncMock()

        async def override_get_db() -> AsyncGenerator[AsyncMock]:
            yield mock_session

        app.dependency_overrides[get_db] = override_get_db
        yield mock_session
        app.dependency_overrides.pop(get_db, None)

    @pytest.fixture
    def activity_client(self) -> Generator[APITestClient]:
        """Test client for activity endpoint tests."""
        with APITestClient(app) as client:
            yield client

    def _patch_activity(
        self,
        sessions: list[MagicMock],
        events_by_session: dict[str, list],
        msg_counts: dict[str, int],
        activity_db: AsyncMock,
    ):
        """Context manager that patches the activity module helpers.

        Patches _build_session_query to return the real SQLAlchemy query,
        but mocks db.execute so no DB call is made.  Also patches the
        preview/count fetchers directly.
        """
        from app.api.persona.activity import ActivityEventPreview

        # Convert raw events to ActivityEventPreview objects
        preview_map: dict[str, list[ActivityEventPreview]] = {}
        for sid, evts in events_by_session.items():
            preview_map[sid] = [
                ActivityEventPreview(
                    event_type=e.event_type,
                    tool_name=e.tool_name,
                    content_preview=e.content[:200] if e.content else None,
                )
                for e in evts
            ]

        total = len(sessions)

        # count query result
        count_result = MagicMock()
        count_result.scalar.return_value = total

        # paginated sessions result
        sessions_result = MagicMock()
        sessions_result.scalars.return_value.all.return_value = sessions

        activity_db.execute = AsyncMock(
            side_effect=[count_result, sessions_result]
        )

        return (
            patch(
                "app.api.persona.activity._fetch_event_previews",
                new_callable=AsyncMock,
                return_value=preview_map,
            ),
            patch(
                "app.api.persona.activity._fetch_message_counts",
                new_callable=AsyncMock,
                return_value=msg_counts,
            ),
        )

    def test_activity_excludes_session_without_events(
        self, activity_client: APITestClient, activity_db: AsyncMock
    ) -> None:
        """A persona session with NO events must not appear in the response.

        We simulate the has_events filter by providing only the session
        that has events in the mocked query results -- the empty session
        is excluded at the SQL level.
        """
        # Arrange
        session_with_events = _make_mock_session("sess-with-events")
        event = _make_mock_event("sess-with-events")

        patch_previews, patch_counts = self._patch_activity(
            sessions=[session_with_events],
            events_by_session={"sess-with-events": [event]},
            msg_counts={"sess-with-events": 1},
            activity_db=activity_db,
        )

        with patch_previews, patch_counts:
            response = activity_client.get("/api/persona/activity?time_range=all")

        # Assert
        assert response.status_code == 200
        data = response.json()
        session_ids = [s["id"] for s in data["sessions"]]
        assert "sess-with-events" in session_ids
        # sess-empty never appeared because has_events filtered it out
        assert data["total"] == 1

    def test_activity_includes_session_with_events(
        self, activity_client: APITestClient, activity_db: AsyncMock
    ) -> None:
        """A persona session with at least one event must appear in the response."""
        session = _make_mock_session("sess-active")
        event = _make_mock_event("sess-active", content="Working on something")

        patch_previews, patch_counts = self._patch_activity(
            sessions=[session],
            events_by_session={"sess-active": [event]},
            msg_counts={"sess-active": 1},
            activity_db=activity_db,
        )

        with patch_previews, patch_counts:
            response = activity_client.get("/api/persona/activity?time_range=all")

        assert response.status_code == 200
        data = response.json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["id"] == "sess-active"
        assert data["sessions"][0]["events_preview"][0]["content_preview"] == "Working on something"

    def test_activity_returns_only_sessions_with_events(
        self, activity_client: APITestClient, activity_db: AsyncMock
    ) -> None:
        """Given a mix of empty and non-empty sessions, only non-empty ones appear.

        The has_events filter in _build_session_query excludes sess-empty at
        the SQL level, so the mocked execute returns only sess-1 and sess-2.
        """
        s1 = _make_mock_session("sess-1")
        s2 = _make_mock_session("sess-2")
        e1 = _make_mock_event("sess-1", content="First event")
        e2 = _make_mock_event(
            "sess-2",
            event_type=SessionEventType.TOOL_USE,
            tool_name="web_search",
            content=None,
        )

        patch_previews, patch_counts = self._patch_activity(
            sessions=[s1, s2],
            events_by_session={"sess-1": [e1], "sess-2": [e2]},
            msg_counts={"sess-1": 1},
            activity_db=activity_db,
        )

        with patch_previews, patch_counts:
            response = activity_client.get("/api/persona/activity?time_range=all")

        assert response.status_code == 200
        data = response.json()
        session_ids = [s["id"] for s in data["sessions"]]
        assert sorted(session_ids) == ["sess-1", "sess-2"]
        assert "sess-empty" not in session_ids
        assert data["total"] == 2
        # sess-1 has a message count, sess-2 does not
        sess_1_data = next(s for s in data["sessions"] if s["id"] == "sess-1")
        sess_2_data = next(s for s in data["sessions"] if s["id"] == "sess-2")
        assert sess_1_data["message_count"] == 1
        assert sess_2_data["message_count"] == 0
