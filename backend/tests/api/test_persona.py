"""Tests for persona API endpoints (app/api/persona.py)."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.api.persona.schemas import PersonaUpdate
from app.db import get_db
from app.main import app
from app.models.persona import Persona
from app.models.persona_scheduled_job import PersonaScheduledJob
from app.models.session import Session, SessionEvent, SessionEventType
from tests.conftest import APITestClient


def _make_persona(**overrides) -> MagicMock:
    """Create a mock Persona with sensible defaults."""
    defaults = {
        "id": 1,
        "agent_id": 10,
        "name": "Persona",
        "personality": "I'm a helpful AI.",
        "heartbeat_instructions": "Check health.",
        "user_context": "User likes brevity.",
        "voice_id": "en-US-AriaNeural",
        "voice_enabled": False,
        "heartbeat_interval_minutes": 60,
        "execution_state": "active",
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


@contextmanager
def _patch_persona_instruction_prompt(persona: MagicMock):
    """Only heartbeat guidance remains prompt-backed; row fields need no mock."""
    with patch(
        "app.api.persona.helpers.get_persona_heartbeat_instructions",
        new=AsyncMock(return_value=persona.heartbeat_instructions),
    ):
        yield


class TestPersonaSchemaValidation:
    """Tests for persona API schema validation."""

    def test_persona_update_accepts_positive_max_turns(self) -> None:
        update = PersonaUpdate(limits={"max_turns": 750})

        assert update.limits is not None
        assert update.limits.max_turns == 750

    def test_persona_update_rejects_zero_max_turns(self) -> None:
        with pytest.raises(ValidationError):
            PersonaUpdate(limits={"max_turns": 0})


class TestGetPersonaEndpoint:
    """Tests for GET /api/persona."""

    def test_returns_persona_response(self, api_client, mock_db_session):
        persona = _make_persona()

        with (
            patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock,
            _patch_persona_instruction_prompt(persona),
        ):
            mock.return_value = persona
            response = api_client.get("/api/persona")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["name"] == "Persona"
        assert data["personality"] == "I'm a helpful AI."
        assert data["version"] == 2
        assert data["agent_slug"] == "persona"
        assert data["onboarding_phase"] == "complete"
        assert data["execution_state"] == "active"
        assert data["session_reset_mode"] == "off"
        assert data["session_reset_hour"] == 9
        assert data["session_reset_idle_minutes"] == 120

    def test_migrates_legacy_user_context_into_structured_profile(self, api_client, mock_db_session):
        persona = _make_persona(
            user_profile=None,
            user_context="# User Profile: Elias\n\n## Identity\n- Name: Elias\n",
        )

        async def _migrate(*_args, **_kwargs):
            persona.user_profile = {
                "user_identity": "- Name: Elias",
                "timezone": "America/New_York",
            }
            persona.user_context = "## Identity Review\n- Name approved"
            return True

        with (
            patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock_get_persona,
            patch(
                "app.api.persona.migrate_legacy_user_context_to_profile",
                new=AsyncMock(side_effect=_migrate),
            ) as mock_migrate,
            patch(
                "app.api.persona.commit_and_refresh",
                new=AsyncMock(return_value=persona),
            ) as mock_commit,
            patch(
                "app.api.persona.helpers.get_persona_heartbeat_instructions",
                new=AsyncMock(side_effect=lambda _db: persona.heartbeat_instructions),
            ),
        ):
            mock_get_persona.return_value = persona
            response = api_client.get("/api/persona")

        assert response.status_code == 200
        data = response.json()
        assert data["user_profile"]["user_identity"] == "- Name: Elias"
        assert data["user_profile"]["timezone"] == "America/New_York"
        assert data["user_context"] == "## Identity Review\n- Name approved"
        mock_migrate.assert_awaited_once()
        mock_commit.assert_awaited_once()


class TestUpdatePersonaEndpoint:
    """Tests for PUT /api/persona."""

    def test_partial_update(self, api_client, mock_db_session):
        persona = _make_persona(version=2)

        with (
            patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock,
            patch(
                "app.api.persona.sync_persona_name_to_agent",
                new=AsyncMock(),
            ) as mock_sync_name,
            patch("app.api.persona.get_agent_service") as mock_get_agent_service,
        ):
            mock_service = MagicMock()
            mock_service.invalidate_slug = AsyncMock()
            mock_get_agent_service.return_value = mock_service
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
        mock_sync_name.assert_awaited_once_with(mock_db_session, persona)
        mock_service.invalidate_slug.assert_awaited_once_with("persona")

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

    def test_can_pause_persona_execution(self, api_client, mock_db_session):
        persona = _make_persona(version=5, execution_state="active")

        with patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock:
            mock.return_value = persona
            response = api_client.put(
                "/api/persona",
                json={"execution_state": "paused"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["execution_state"] == "paused"
        assert data["version"] == 6


class TestPersonaImprovementDashboardEndpoint:
    """Tests for GET /api/persona/improvement."""

    @pytest.mark.parametrize("query", ["days=0", "days=366", "limit=0", "limit=51"])
    def test_rejects_invalid_windows(self, api_client, query):
        """Invalid improvement windows are rejected before dashboard work."""
        response = api_client.get(f"/api/persona/improvement?{query}")

        assert response.status_code == 422

    def test_returns_focused_improvement_dashboard(self, api_client, mock_db_session):
        payload = {
            "generated_at": "2026-03-31T18:00:00Z",
            "suite_id": "persona-suite-self-improvement",
            "days": 30,
            "schedule": {
                "job_id": "job-123",
                "enabled": True,
                "schedule_type": "every",
                "schedule_value": "86400000",
                "schedule_timezone": "UTC",
                "cadence_minutes": 1440,
                "cadence_label": "24h",
                "last_run_at": "2026-03-31T00:00:00Z",
                "next_run_at": "2026-04-01T00:00:00Z",
                "run_count": 12,
            },
            "overview": {
                "total_runs": 12,
                "latest_completed_at": "2026-03-31T17:00:00Z",
                "reliability": 91.2,
                "effectiveness": 84.5,
                "tokens_per_passed_attempt": 1880.4,
                "prompt_tokens": 16780.0,
                "open_regressions": 2,
            },
            "latest_lab_run": {
                "run_id": "run-12",
                "benchmark_id": "persona-benchmark-latest",
                "suite_id": "persona-suite-self-improvement",
                "run_kind": "honing_iteration",
                "started_at": "2026-03-31T16:55:00Z",
                "completed_at": "2026-03-31T17:00:00Z",
                "models": ["codex/gpt-5.4"],
                "case_ids": ["manual_project_access_block"],
                "attempt_count": 9,
                "passed_attempt_count": 9,
                "infra_failure_count": 0,
                "reliability": 100.0,
                "effectiveness": 100.0,
                "avg_total_tokens": 1600.0,
                "tokens_per_passed_attempt": 1600.0,
                "avg_tool_calls": 0.1,
                "avg_turns": 1.0,
                "prompt_tokens": 16780,
                "failure_count": 0,
                "top_failure_detail": None,
                "family_breakdown": [],
                "experiment_decision": None,
                "experiment_decision_reason": None,
                "decision_source": None,
            },
            "field_overview": {
                "total_heartbeats": 4,
                "latest_completed_at": "2026-03-31T17:15:00Z",
                "reliability": 89.0,
                "effectiveness": 83.5,
                "truth_quality": 92.0,
                "tokens_per_healthy_heartbeat": 2460.0,
                "avg_tool_calls": 3.1,
                "avg_turns": 2.3,
                "healthy_heartbeats": 2,
                "healthy_rate": 50.0,
                "risky_heartbeats": 1,
                "critical_heartbeats": 0,
                "action_heartbeats": 2,
                "action_rate": 50.0,
                "ok_heartbeats": 2,
                "ok_rate": 50.0,
                "partial_heartbeats": 0,
                "partial_rate": 0.0,
                "completed_heartbeats": 0,
                "failed_heartbeats": 0,
                "unknown_heartbeats": 0,
                "top_issue_code": "cleanup_actionable",
                "top_issue_label": "cleanup still actionable",
                "top_issue_count": 2,
            },
            "field_window_days": 7,
            "field_window_lab_runs": 5,
            "field_review_gate": {
                "needs_review": True,
                "reason_codes": ["field_repeated_issue"],
                "summary": "repeated field issue needs a source fix",
            },
            "trend": [
                {
                    "run_id": "run-1",
                    "completed_at": "2026-03-31T17:00:00Z",
                    "run_kind": "honing_baseline",
                    "suite_id": "persona-suite-self-improvement",
                    "reliability": 90.0,
                    "effectiveness": 82.0,
                    "avg_total_tokens": 1600.0,
                    "tokens_per_passed_attempt": 1800.0,
                    "avg_tool_calls": 3.2,
                    "avg_turns": 2.1,
                    "prompt_tokens": 16780,
                }
            ],
            "field_trend": [
                {
                    "session_id": "sess-1",
                    "completed_at": "2026-03-31T17:15:00Z",
                    "reliability": 89.0,
                    "effectiveness": 83.5,
                    "truth_quality": 92.0,
                    "total_tokens": 2410,
                    "tool_calls": 3,
                    "turns": 2,
                    "result_status": "action",
                }
            ],
            "recent_runs": [],
            "recent_heartbeats": [],
            "open_regressions": [],
            "field_risks": [],
            "schedule_risks": [],
        }

        with patch(
            "app.api.persona.get_persona_improvement_dashboard",
            new=AsyncMock(return_value=payload),
        ) as mock_dashboard:
            response = api_client.get("/api/persona/improvement?days=30&limit=8")

        assert response.status_code == 200
        data = response.json()
        assert data["suite_id"] == "persona-suite-self-improvement"
        assert data["schedule"]["enabled"] is True
        assert data["overview"]["reliability"] == 91.2
        assert data["latest_lab_run"]["run_id"] == "run-12"
        assert data["field_window_lab_runs"] == 5
        assert data["field_review_gate"]["needs_review"] is True
        mock_dashboard.assert_awaited_once()


class TestPersonaImprovementScheduleEndpoint:
    """Tests for PUT /api/persona/improvement/schedule."""

    def test_schedule_update_schema_defaults_to_15_minutes(self):
        from app.api.persona.schemas import PersonaImprovementScheduleUpdate

        payload = PersonaImprovementScheduleUpdate(enabled=True)

        assert payload.cadence_minutes == 15

    def test_updates_self_honing_schedule(self, api_client, mock_db_session):
        payload = {
            "job_id": "job-123",
            "enabled": True,
            "schedule_type": "every",
            "schedule_value": "43200000",
            "schedule_timezone": "UTC",
            "cadence_minutes": 720,
            "cadence_label": "12h",
            "last_run_at": None,
            "next_run_at": "2026-04-01T00:00:00Z",
            "run_count": 3,
        }

        with patch(
            "app.api.persona.update_persona_self_honing_schedule",
            new=AsyncMock(return_value=payload),
        ) as mock_update:
            response = api_client.put(
                "/api/persona/improvement/schedule",
                json={"enabled": True, "cadence_minutes": 720},
            )

        assert response.status_code == 200
        assert response.json()["cadence_minutes"] == 720
        mock_update.assert_awaited_once()

    def test_returns_validation_error_from_schedule_service(self, api_client, mock_db_session):
        with patch(
            "app.api.persona.update_persona_self_honing_schedule",
            new=AsyncMock(side_effect=ValueError("cadence_minutes must be between 15 and 10080")),
        ) as mock_update:
            response = api_client.put(
                "/api/persona/improvement/schedule",
                json={"enabled": True, "cadence_minutes": 720},
            )

        assert response.status_code == 422
        mock_update.assert_awaited_once()

    def test_no_op_when_empty_update(self, api_client):
        persona = _make_persona(version=2)

        with (
            patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock,
            _patch_persona_instruction_prompt(persona),
        ):
            mock.return_value = persona
            response = api_client.put("/api/persona", json={})

        assert response.status_code == 200
        assert response.json()["version"] == 2  # not incremented


class TestResetOnboardingEndpoint:
    """Tests for POST /api/persona/reset-onboarding."""

    def test_resets_onboarding_flag_and_phase(self, api_client, mock_db_session):
        persona = _make_persona(onboarding_complete=True, onboarding_phase="complete", version=3)

        with (
            patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock,
            _patch_persona_instruction_prompt(persona),
            patch(
                "app.api.persona.clear_persona_user_context_document",
                new=AsyncMock(),
            ) as mock_clear,
        ):
            mock.return_value = persona
            response = api_client.post("/api/persona/reset-onboarding")

        assert response.status_code == 200
        data = response.json()
        assert data["onboarding_complete"] is False
        assert data["onboarding_phase"] == "not_started"
        assert data["version"] == 4  # incremented
        mock_clear.assert_awaited_once()


class TestGetPersonalityEndpoint:
    """Tests for GET /api/persona/personality."""

    def test_returns_personality_and_version(self, api_client, mock_db_session):
        persona = _make_persona(personality="Creative and bold.", version=7)

        with (
            patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock,
            _patch_persona_instruction_prompt(persona),
        ):
            mock.return_value = persona
            response = api_client.get("/api/persona/personality")

        assert response.status_code == 200
        data = response.json()
        assert data["personality"] == "Creative and bold."
        assert data["version"] == 7

    def test_returns_null_personality_when_not_set(self, api_client, mock_db_session):
        persona = _make_persona(personality=None)

        with (
            patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock,
            _patch_persona_instruction_prompt(persona),
        ):
            mock.return_value = persona
            response = api_client.get("/api/persona/personality")

        assert response.status_code == 200
        assert response.json()["personality"] is None


class TestUpdatePersonalityEndpoint:
    """Tests for PUT /api/persona/personality."""

    def test_updates_personality(self, api_client, mock_db_session):
        persona = _make_persona(version=3)

        async def _set_personality(_db, value, **_kwargs):
            old_value = persona.personality or ""
            persona.personality = value
            return len(old_value), len(value)

        with (
            patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock,
            patch(
                "app.api.persona.set_persona_personality_document",
                new=AsyncMock(side_effect=_set_personality),
            ) as mock_set,
            patch(
                "app.api.persona.helpers.get_persona_heartbeat_instructions",
                new=AsyncMock(return_value=persona.heartbeat_instructions),
            ),
        ):
            mock.return_value = persona
            response = api_client.put(
                "/api/persona/personality",
                json={"personality": "New personality text.", "reason": "Testing"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["personality"] == "New personality text."
        assert data["version"] == 4
        mock_set.assert_awaited_once()

    def test_updates_personality_without_reason(self, api_client, mock_db_session):
        persona = _make_persona(version=1)

        async def _set_personality(_db, value, **_kwargs):
            old_value = persona.personality or ""
            persona.personality = value
            return len(old_value), len(value)

        with (
            patch("app.api.persona.get_or_create_persona", new_callable=AsyncMock) as mock,
            patch(
                "app.api.persona.set_persona_personality_document",
                new=AsyncMock(side_effect=_set_personality),
            ) as mock_set,
            patch(
                "app.api.persona.helpers.get_persona_heartbeat_instructions",
                new=AsyncMock(return_value=persona.heartbeat_instructions),
            ),
        ):
            mock.return_value = persona
            response = api_client.put(
                "/api/persona/personality",
                json={"personality": "Updated."},
            )

        assert response.status_code == 200
        assert response.json()["version"] == 2
        mock_set.assert_awaited_once()


# ---------------------------------------------------------------------------
# Activity endpoint — empty-session filter
# ---------------------------------------------------------------------------


def _make_mock_session(session_id: str, **overrides: Any) -> MagicMock:
    """Create a mock Session with sensible defaults for activity tests."""
    now = datetime.now(UTC)
    defaults: dict[str, Any] = {
        "id": session_id,
        "agent_slug": "persona",
        "project_id": "persona-sandbox",
        "session_type": "chat",
        "summary_oneliner": None,
        "parent_session_id": None,
        "current_branch": None,
        "external_id": None,
        "provider_metadata": {},
        "model": "claude-sonnet",
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


class TestActivitySessionClassification:
    """Unit tests for activity-specific session type classification."""

    def test_persona_sandbox_completion_maps_to_heartbeat(self) -> None:
        from app.api.persona.activity import _classify_activity_session_type

        session = _make_mock_session(
            "heartbeat-1",
            project_id="persona-sandbox",
            session_type="completion",
        )

        assert _classify_activity_session_type(session) == "heartbeat"

    def test_non_sandbox_completion_remains_completion(self) -> None:
        from app.api.persona.activity import _classify_activity_session_type

        session = _make_mock_session(
            "scheduled-1",
            project_id="agent-hub",
            session_type="completion",
        )

        assert _classify_activity_session_type(session) == "completion"


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

        event_counts = {
            session_id: len(previews)
            for session_id, previews in preview_map.items()
        }

        return (
            patch(
                "app.api.persona.activity._fetch_event_previews",
                new_callable=AsyncMock,
                return_value=preview_map,
            ),
            patch(
                "app.api.persona.activity._fetch_session_counts",
                new_callable=AsyncMock,
                return_value=(msg_counts, event_counts),
            ),
            patch(
                "app.api.persona.activity._fetch_child_counts",
                new_callable=AsyncMock,
                return_value=({}, {}),
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

        patch_previews, patch_counts, patch_child_counts = self._patch_activity(
            sessions=[session_with_events],
            events_by_session={"sess-with-events": [event]},
            msg_counts={"sess-with-events": 1},
            activity_db=activity_db,
        )

        with patch_previews, patch_counts, patch_child_counts:
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

        patch_previews, patch_counts, patch_child_counts = self._patch_activity(
            sessions=[session],
            events_by_session={"sess-active": [event]},
            msg_counts={"sess-active": 1},
            activity_db=activity_db,
        )

        with patch_previews, patch_counts, patch_child_counts:
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

        patch_previews, patch_counts, patch_child_counts = self._patch_activity(
            sessions=[s1, s2],
            events_by_session={"sess-1": [e1], "sess-2": [e2]},
            msg_counts={"sess-1": 1},
            activity_db=activity_db,
        )

        with patch_previews, patch_counts, patch_child_counts:
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

    def test_activity_maps_persona_sandbox_completion_to_heartbeat(
        self, activity_client: APITestClient, activity_db: AsyncMock
    ) -> None:
        session = _make_mock_session(
            "sess-heartbeat",
            project_id="persona-sandbox",
            session_type="completion",
        )
        event = _make_mock_event("sess-heartbeat", content="Heartbeat event")

        patch_previews, patch_counts, patch_child_counts = self._patch_activity(
            sessions=[session],
            events_by_session={"sess-heartbeat": [event]},
            msg_counts={"sess-heartbeat": 1},
            activity_db=activity_db,
        )

        with patch_previews, patch_counts, patch_child_counts:
            response = activity_client.get("/api/persona/activity?time_range=all")

        assert response.status_code == 200
        assert response.json()["sessions"][0]["session_type"] == "heartbeat"

    def test_activity_leaves_non_sandbox_completion_as_completion(
        self, activity_client: APITestClient, activity_db: AsyncMock
    ) -> None:
        session = _make_mock_session(
            "sess-scheduled",
            project_id="agent-hub",
            session_type="completion",
        )
        event = _make_mock_event("sess-scheduled", content="Scheduled job")

        patch_previews, patch_counts, patch_child_counts = self._patch_activity(
            sessions=[session],
            events_by_session={"sess-scheduled": [event]},
            msg_counts={"sess-scheduled": 1},
            activity_db=activity_db,
        )

        with patch_previews, patch_counts, patch_child_counts:
            response = activity_client.get("/api/persona/activity?time_range=all")

        assert response.status_code == 200
        assert response.json()["sessions"][0]["session_type"] == "completion"


class TestPersonaStreamHelpers:
    """Tests for the unified persona stream helper logic."""

    def test_stringify_preview_serializes_tool_payloads(self) -> None:
        from app.api.persona.stream import _stringify_preview

        assert _stringify_preview({"project": "agent-hub"}) == '{"project": "agent-hub"}'
        truncated = _stringify_preview({"status": "ok", "items": [1, 2]}, limit=18)
        assert truncated is not None
        assert truncated.endswith("…")
        assert truncated.startswith('{"items": [1')
        assert _stringify_preview(None) is None

    @pytest.mark.asyncio
    async def test_fetch_event_previews_preserves_full_issue_text_for_issue_events(self) -> None:
        from app.api.persona.stream import _fetch_event_previews

        issue_text = (
            'git status --short --branch && st context task-123 && st done task-123 --message '
            '"Verified autocode completion; quality gate passed." after repeated retries before success.'
        )
        event = _make_mock_event(
            "child-1",
            id="preview-issue",
            event_type=SessionEventType.TOOL_RESULT,
            tool_name="shell",
            content=None,
            tool_input={"command": issue_text},
            tool_output={"status": "failed", "stderr": issue_text, "exit_code": 1, "is_error": True},
            created_at=datetime.now(UTC),
            role=None,
            model_used="claude-sonnet",
        )
        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = [event]
        db = AsyncMock()
        db.execute.return_value = execute_result

        previews = await _fetch_event_previews(db, ["child-1"])

        assert previews["child-1"][0].tool_input_preview is not None
        assert "quality gate passed" in previews["child-1"][0].tool_input_preview
        assert previews["child-1"][0].tool_output_preview is not None
        assert "quality gate passed" in previews["child-1"][0].tool_output_preview

    def test_build_stream_entries_includes_messages_heartbeats_and_child_runs(self) -> None:
        from app.api.persona.pulse import SessionPulse
        from app.api.persona.schemas import PersonaIssueMarker, PersonaStreamEventPreview
        from app.api.persona.stream import _build_stream_entries

        base_time = datetime.now(UTC)
        chat_session = _make_mock_session(
            "chat-1",
            session_type="chat",
            project_id="persona-sandbox",
            created_at=base_time - timedelta(minutes=3),
        )
        heartbeat_session = _make_mock_session(
            "hb-1",
            session_type="completion",
            project_id="persona-sandbox",
            summary_oneliner="HEARTBEAT_ACTION - fixed issue",
            provider_metadata={"live_activity": {"summary": "Checking tasks", "status": "active"}},
            created_at=base_time - timedelta(minutes=2),
        )
        child_session = _make_mock_session(
            "child-1",
            agent_slug="git-agent",
            project_id="agent-hub",
            parent_session_id="hb-1",
            summary_oneliner="Updated files",
            current_branch="task-branch",
            created_at=base_time - timedelta(minutes=1),
        )
        event = _make_mock_event(
            "chat-1",
            id="evt-1",
            role="user",
            content="pause that work",
            created_at=base_time - timedelta(minutes=4),
            model_used="claude-sonnet",
        )

        entries = _build_stream_entries(
            persona_sessions=[chat_session, heartbeat_session],
            child_sessions=[child_session],
            message_events=[event],
            message_counts={"chat-1": 2, "hb-1": 1, "child-1": 3},
            tool_counts={"chat-1": 0, "hb-1": 4, "child-1": 2},
            event_previews={
                "hb-1": [
                    PersonaStreamEventPreview(
                        id="preview-1",
                        event_type="tool_use",
                        created_at=base_time - timedelta(minutes=2),
                        tool_name="st ready-all",
                        content_preview=None,
                        tool_input_preview='{"project":"agent-hub"}',
                        tool_output_preview=None,
                        duration_ms=None,
                        model_used="claude-sonnet",
                    )
                ],
                "child-1": [
                    PersonaStreamEventPreview(
                        id="preview-2",
                        event_type="tool_result",
                        created_at=base_time - timedelta(minutes=1),
                        tool_name="dt -q -d",
                        content_preview="passed",
                        tool_input_preview=None,
                        tool_output_preview='{"status":"ok"}',
                        duration_ms=1200,
                        model_used="claude-sonnet",
                    )
                ],
            },
            session_pulses={
                "hb-1": SessionPulse(
                    issue_markers=[
                        PersonaIssueMarker(
                            event_id="preview-1",
                            event_type="tool_use",
                            created_at=base_time - timedelta(minutes=2),
                            tool_name="st ready-all",
                            tags=["warning"],
                            primary_tag="warning",
                            root_causes=["context"],
                            primary_root_cause="context",
                            title="Work stalled waiting on context or follow-up",
                            summary="The run waited on follow-up.",
                            detail="The run waited on follow-up.",
                            fingerprint="warning:context",
                        )
                    ],
                    tags=["friction", "warning"],
                    primary_tag="warning",
                    root_causes=["context"],
                    primary_root_cause="context",
                    summary="completed with warnings",
                ),
                "child-1": SessionPulse(
                    issue_markers=[
                        PersonaIssueMarker(
                            event_id="preview-2",
                            event_type="tool_result",
                            created_at=base_time - timedelta(minutes=1),
                            tool_name="dt -q -d",
                            tags=["tool_friction"],
                            primary_tag="tool_friction",
                            root_causes=["tool"],
                            primary_root_cause="tool",
                            title="dt -q -d hit tool friction",
                            summary="The tool path wasted turns before progress resumed.",
                            detail="The tool path wasted turns before progress resumed.",
                            fingerprint="tool-friction:dt-q-d",
                        )
                    ],
                    tags=["friction", "tool_friction", "retries"],
                    primary_tag="tool_friction",
                    root_causes=["tool"],
                    primary_root_cause="tool",
                    summary="tool friction detected",
                ),
            },
            display_summaries={
                "hb-1": "Checked active work across queue, cleanup, and session truth.",
                "child-1": "Updated files and verified the result.",
            },
        )

        assert [entry.entry_type for entry in entries] == ["child_run", "heartbeat", "message"]
        heartbeat_entry = next(entry for entry in entries if entry.entry_type == "heartbeat")
        child_entry = next(entry for entry in entries if entry.entry_type == "child_run")
        message_entry = next(entry for entry in entries if entry.entry_type == "message")

        assert message_entry.content == "pause that work"
        assert heartbeat_entry.session_type == "heartbeat"
        assert heartbeat_entry.display_summary == "Checked active work across queue, cleanup, and session truth."
        assert heartbeat_entry.live_summary == "Checking tasks"
        assert heartbeat_entry.event_previews[0].tool_name == "st ready-all"
        assert heartbeat_entry.event_previews[0].tool_input_preview == '{"project":"agent-hub"}'
        assert heartbeat_entry.issue_markers[0].title == "Work stalled waiting on context or follow-up"
        assert heartbeat_entry.pulse_tags == ["friction", "warning"]
        assert heartbeat_entry.primary_root_cause == "context"
        assert child_entry.agent_slug == "git-agent"
        assert child_entry.current_branch == "task-branch"
        assert child_entry.display_summary == "Updated files and verified the result."
        assert child_entry.event_previews[0].content_preview == "passed"
        assert child_entry.event_previews[0].tool_output_preview == '{"status":"ok"}'
        assert child_entry.issue_markers[0].fingerprint == "tool-friction:dt-q-d"
        assert child_entry.primary_pulse_tag == "tool_friction"
        assert child_entry.pulse_summary == "tool friction detected"

    def test_classify_session_pulse_builds_issue_markers_from_previews(self) -> None:
        from app.api.persona.pulse import classify_session_pulse
        from app.api.persona.schemas import PersonaStreamEventPreview

        session = _make_mock_session(
            "child-1",
            agent_slug="git-agent",
            project_id="agent-hub",
            status="completed",
            created_at=datetime.now(UTC) - timedelta(minutes=3),
            updated_at=datetime.now(UTC),
        )
        previews = [
            PersonaStreamEventPreview(
                id="preview-1",
                event_type=SessionEventType.TOOL_USE,
                created_at=datetime.now(UTC) - timedelta(minutes=3),
                tool_name="shell",
                content_preview=None,
                tool_input_preview='{"command": "pytest tests/api/test_persona.py"}',
                tool_output_preview=None,
                duration_ms=None,
                model_used="claude-sonnet",
            ),
            PersonaStreamEventPreview(
                id="preview-2",
                event_type=SessionEventType.TOOL_RESULT,
                created_at=datetime.now(UTC) - timedelta(minutes=2),
                tool_name="shell",
                content_preview=None,
                tool_input_preview=None,
                tool_output_preview='{"status": "failed", "stderr": "dt not found", "exit_code": 1, "is_error": true}',
                duration_ms=300,
                model_used="claude-sonnet",
            ),
            PersonaStreamEventPreview(
                id="preview-3",
                event_type=SessionEventType.TOOL_RESULT,
                created_at=datetime.now(UTC) - timedelta(minutes=1),
                tool_name="dt -q -d",
                content_preview="Checks passed",
                tool_input_preview=None,
                tool_output_preview='{"status": "ok", "content": "Checks passed", "exit_code": 0}',
                duration_ms=500,
                model_used="claude-sonnet",
            ),
        ]

        pulse = classify_session_pulse(session, previews)

        assert "friction" in pulse.tags
        assert "instruction_drift" in pulse.tags
        assert "tool_friction" in pulse.tags
        assert "recovered" in pulse.tags
        assert pulse.primary_tag == "instruction_drift"
        assert pulse.primary_root_cause == "workflow"
        assert pulse.summary is not None
        assert "recovered before completion" in pulse.summary.lower()
        assert any(marker.primary_tag == "instruction_drift" for marker in pulse.issue_markers)
        assert any(marker.title == "shell failed" for marker in pulse.issue_markers)
        shell_failed_marker = next(marker for marker in pulse.issue_markers if marker.title == "shell failed")
        assert shell_failed_marker.detail is not None
        assert "dt not found" in shell_failed_marker.detail
        instruction_marker = next(marker for marker in pulse.issue_markers if marker.primary_tag == "instruction_drift")
        assert instruction_marker.detail is not None
        assert "pytest tests/api/test_persona.py" in instruction_marker.detail

    def test_classify_session_pulse_skips_summary_marker_when_event_issue_exists(self) -> None:
        from app.api.persona.pulse import classify_session_pulse
        from app.api.persona.schemas import PersonaStreamEventPreview

        session = _make_mock_session(
            "hb-1",
            agent_slug="persona",
            project_id="persona-sandbox",
            status="completed",
            summary_oneliner="Completed with warnings while reviewing task-605a52fc",
            created_at=datetime.now(UTC) - timedelta(minutes=3),
            updated_at=datetime.now(UTC),
        )
        previews = [
            PersonaStreamEventPreview(
                id="preview-warning",
                event_type=SessionEventType.ASSISTANT_MESSAGE,
                created_at=datetime.now(UTC) - timedelta(minutes=1),
                tool_name=None,
                content_preview='Blocked on follow-up\nTASK:task-605a52fc|pending|P2|task|STANDARD\nTITLE:Live validation\nDESCRIPTION:Temporary validation task\nWORKFLOW:plan:approved|ready:yes|issues:0|decisions:1',
                tool_input_preview=None,
                tool_output_preview=None,
                duration_ms=None,
                model_used="claude-sonnet",
            )
        ]

        pulse = classify_session_pulse(session, previews)

        assert len(pulse.issue_markers) == 1
        assert pulse.issue_markers[0].event_type != "session_summary"

    def test_classify_session_pulse_does_not_flag_retries_for_distinct_manage_tasks_inputs(self) -> None:
        from app.api.persona.pulse import classify_session_pulse
        from app.api.persona.schemas import PersonaStreamEventPreview

        session = _make_mock_session(
            "hb-2",
            agent_slug="persona",
            project_id="persona-sandbox",
            status="completed",
            created_at=datetime.now(UTC) - timedelta(minutes=3),
            updated_at=datetime.now(UTC),
        )
        previews = [
            PersonaStreamEventPreview(
                id="preview-task-a",
                event_type=SessionEventType.TOOL_RESULT,
                created_at=datetime.now(UTC) - timedelta(minutes=2),
                tool_name="manage_tasks",
                content_preview=None,
                tool_input_preview='{"action":"reconcile","task_id":"task-a"}',
                tool_output_preview='{"status":"error","content":"Diff gate blocked completion","is_error":true}',
                duration_ms=300,
                model_used="codex/gpt-5.4",
            ),
            PersonaStreamEventPreview(
                id="preview-task-b",
                event_type=SessionEventType.TOOL_RESULT,
                created_at=datetime.now(UTC) - timedelta(minutes=1),
                tool_name="manage_tasks",
                content_preview=None,
                tool_input_preview='{"action":"reconcile","task_id":"task-b"}',
                tool_output_preview='{"status":"error","content":"Diff gate blocked completion","is_error":true}',
                duration_ms=320,
                model_used="codex/gpt-5.4",
            ),
        ]

        pulse = classify_session_pulse(session, previews)

        assert "retries" not in pulse.tags
        assert not any("retries" in marker.tags for marker in pulse.issue_markers)

    def test_build_pulse_summary_groups_repeated_issue_fingerprints(self) -> None:
        from app.api.persona.pulse import SessionPulse, build_pulse_summary
        from app.api.persona.schemas import PersonaIssueMarker, PersonaStreamEntry

        base_time = datetime.now(UTC)
        sessions = [
            _make_mock_session(
                "child-1",
                agent_slug="git-agent",
                project_id="agent-hub",
                status="completed",
                created_at=base_time - timedelta(minutes=5),
                updated_at=base_time - timedelta(minutes=4),
            ),
            _make_mock_session(
                "child-2",
                agent_slug="git-agent",
                project_id="agent-hub",
                status="completed",
                created_at=base_time - timedelta(minutes=3),
                updated_at=base_time - timedelta(minutes=2),
            ),
        ]
        entries = [
            PersonaStreamEntry(
                id="child-child-1",
                entry_type="child_run",
                timestamp=base_time - timedelta(minutes=5),
                session_id="child-1",
                parent_session_id="hb-1",
                project_id="agent-hub",
                agent_slug="git-agent",
                session_type="completion",
                status="completed",
                issue_markers=[
                    PersonaIssueMarker(
                        event_id="preview-1",
                        event_type="tool_result",
                        created_at=base_time - timedelta(minutes=5),
                        tool_name="dt -q -d",
                        tags=["tool_friction"],
                        primary_tag="tool_friction",
                        root_causes=["tool"],
                        primary_root_cause="tool",
                        title="dt -q -d hit tool friction",
                        summary="The tool path wasted turns before progress resumed.",
                        detail="The tool path wasted turns before progress resumed.",
                        fingerprint="tool-friction:dt-q-d",
                    )
                ],
                pulse_tags=["friction", "tool_friction"],
                primary_pulse_tag="tool_friction",
                root_causes=["tool"],
                primary_root_cause="tool",
                pulse_summary="dt -q -d hit repeated tool friction",
            ),
            PersonaStreamEntry(
                id="child-child-2",
                entry_type="child_run",
                timestamp=base_time - timedelta(minutes=3),
                session_id="child-2",
                parent_session_id="hb-2",
                project_id="agent-hub",
                agent_slug="git-agent",
                session_type="completion",
                status="completed",
                issue_markers=[
                    PersonaIssueMarker(
                        event_id="preview-2",
                        event_type="tool_result",
                        created_at=base_time - timedelta(minutes=3),
                        tool_name="dt -q -d",
                        tags=["tool_friction"],
                        primary_tag="tool_friction",
                        root_causes=["tool"],
                        primary_root_cause="tool",
                        title="dt -q -d hit tool friction",
                        summary="The tool path wasted turns before progress resumed.",
                        detail="The tool path wasted turns before progress resumed.",
                        fingerprint="tool-friction:dt-q-d",
                    )
                ],
                pulse_tags=["friction", "tool_friction"],
                primary_pulse_tag="tool_friction",
                root_causes=["tool"],
                primary_root_cause="tool",
                pulse_summary="dt -q -d hit repeated tool friction",
            ),
        ]
        session_pulses = {
            "child-1": SessionPulse(
                issue_markers=[
                    PersonaIssueMarker(
                        event_id="preview-1",
                        event_type="tool_result",
                        created_at=base_time - timedelta(minutes=5),
                        tool_name="dt -q -d",
                        tags=["tool_friction"],
                        primary_tag="tool_friction",
                        root_causes=["tool"],
                        primary_root_cause="tool",
                        title="dt -q -d hit tool friction",
                        summary="The tool path wasted turns before progress resumed.",
                        detail="The tool path wasted turns before progress resumed.",
                        fingerprint="tool-friction:dt-q-d",
                    )
                ],
                tags=["friction", "tool_friction"],
                primary_tag="tool_friction",
                root_causes=["tool"],
                primary_root_cause="tool",
                summary="dt -q -d hit repeated tool friction",
            ),
            "child-2": SessionPulse(
                issue_markers=[
                    PersonaIssueMarker(
                        event_id="preview-2",
                        event_type="tool_result",
                        created_at=base_time - timedelta(minutes=3),
                        tool_name="dt -q -d",
                        tags=["tool_friction"],
                        primary_tag="tool_friction",
                        root_causes=["tool"],
                        primary_root_cause="tool",
                        title="dt -q -d hit tool friction",
                        summary="The tool path wasted turns before progress resumed.",
                        detail="The tool path wasted turns before progress resumed.",
                        fingerprint="tool-friction:dt-q-d",
                    )
                ],
                tags=["friction", "tool_friction"],
                primary_tag="tool_friction",
                root_causes=["tool"],
                primary_root_cause="tool",
                summary="dt -q -d hit repeated tool friction",
            ),
        }

        pulse = build_pulse_summary(entries, sessions, session_pulses)

        assert pulse.metrics[0].key == "friction"
        assert pulse.metrics[0].count == 2
        assert pulse.issue_groups[0].fingerprint == "tool-friction:dt-q-d"
        assert pulse.issue_groups[0].count == 2
        assert pulse.issue_groups[0].title == "dt -q -d hit tool friction"
        assert pulse.agent_scorecards[0].agent_slug == "git-agent"
        assert pulse.agent_scorecards[0].tool_friction_count == 2

    def test_slice_entries_centers_on_focused_session(self) -> None:
        from app.api.persona.schemas import PersonaStreamEntry
        from app.api.persona.stream import _slice_entries

        base_time = datetime.now(UTC)
        entries = [
            PersonaStreamEntry(
                id=f"e-{idx}",
                entry_type="message",
                timestamp=base_time,
                session_id=f"s-{idx}",
                project_id="persona-sandbox",
                agent_slug="persona",
                session_type="chat",
                status="completed",
                role="user",
                content=f"msg {idx}",
            )
            for idx in range(10)
        ]

        sliced = _slice_entries(
            entries,
            page=1,
            page_size=4,
            focus_session_id="s-5",
            anchor_entry_id=None,
        )

        assert [entry.session_id for entry in sliced] == ["s-3", "s-4", "s-5", "s-6"]

    def test_slice_entries_centers_on_anchor_entry(self) -> None:
        from app.api.persona.schemas import PersonaStreamEntry
        from app.api.persona.stream import _slice_entries

        base_time = datetime.now(UTC)
        entries = [
            PersonaStreamEntry(
                id=f"e-{idx}",
                entry_type="heartbeat",
                timestamp=base_time - timedelta(minutes=idx),
                session_id=f"s-{idx}",
                project_id="persona-sandbox",
                agent_slug="persona",
                session_type="heartbeat",
                status="completed",
            )
            for idx in range(10)
        ]

        sliced = _slice_entries(
            entries,
            page=1,
            page_size=4,
            focus_session_id=None,
            anchor_entry_id="e-6",
        )

        assert [entry.id for entry in sliced] == ["e-4", "e-5", "e-6", "e-7"]

    def test_build_search_matches_returns_entry_metadata(self) -> None:
        from app.api.persona.schemas import PersonaStreamEntry
        from app.api.persona.stream import _build_search_matches, _parse_search

        base_time = datetime.now(UTC)
        entries = [
            PersonaStreamEntry(
                id="msg-1",
                entry_type="message",
                timestamp=base_time,
                session_id="chat-1",
                project_id="persona-sandbox",
                agent_slug="persona",
                session_type="chat",
                status="completed",
                role="assistant",
                content="I am verifying task-123 now",
            ),
            PersonaStreamEntry(
                id="hb-1",
                entry_type="heartbeat",
                timestamp=base_time - timedelta(minutes=1),
                session_id="hb-1",
                project_id="persona-sandbox",
                agent_slug="persona",
                session_type="heartbeat",
                status="completed",
                summary_oneliner="Checked active work",
            ),
        ]

        matches, match_count = _build_search_matches(entries, parsed_search=_parse_search("task:task-123"))

        assert match_count == 1
        assert len(matches) == 1
        assert matches[0].entry_id == "msg-1"
        assert matches[0].session_id == "chat-1"
        assert "task-123" in matches[0].snippet

    def test_parse_search_supports_structured_tokens(self) -> None:
        from app.api.persona.stream import _parse_search

        parsed = _parse_search("agent:git-agent status:failed task:task-123 verify bug")

        assert parsed.agent_terms == ["git-agent"]
        assert parsed.status_terms == ["failed"]
        assert parsed.task_terms == ["task-123"]
        assert parsed.general_terms == ["verify", "bug"]


class TestPersonaAutomationEndpoints:
    """Tests for persona automation CRUD."""

    def test_lists_persona_automations(self, api_client, mock_db_session):
        persona = _make_persona(id=7)
        job = PersonaScheduledJob(
            id="job-1",
            persona_id=7,
            name="Nightly review",
            schedule_type="cron",
            schedule_value="0 9 * * *",
            schedule_timezone="UTC",
            payload_type="agent_turn",
            payload_message="Run nightly review and report back in persona workspace.",
            delivery="none",
            enabled=True,
            last_run_at=datetime(2026, 4, 14, 9, 0, tzinfo=UTC),
            next_run_at=datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
            run_count=3,
            max_runs=None,
            created_at=datetime(2026, 4, 10, 9, 0, tzinfo=UTC),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [job]
        mock_db_session.execute.return_value = mock_result

        with patch("app.api.persona.automations.get_or_create_persona", new=AsyncMock(return_value=persona)):
            response = api_client.get("/api/persona/automations")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "job-1"
        assert data[0]["name"] == "Nightly review"
        assert data[0]["payload_message"] == "Run nightly review and report back in persona workspace."

    def test_creates_persona_automation(self, api_client, mock_db_session):
        persona = _make_persona(id=7)
        next_run = datetime(2026, 4, 16, 14, 0, tzinfo=UTC)

        async def _refresh(job: PersonaScheduledJob) -> None:
            job.id = "job-created"
            if job.created_at is None:
                job.created_at = datetime(2026, 4, 15, 14, 0, tzinfo=UTC)

        mock_db_session.refresh = _refresh

        with (
            patch("app.api.persona.automations.get_or_create_persona", new=AsyncMock(return_value=persona)),
            patch("app.api.persona.automations.compute_next_run", return_value=next_run),
        ):
            response = api_client.post(
                "/api/persona/automations",
                json={
                    "name": "Morning status",
                    "schedule_type": "every",
                    "schedule_value": "3600000",
                    "schedule_timezone": "UTC",
                    "payload_type": "agent_turn",
                    "payload_message": "Check active work and post concise status back into persona workspace.",
                    "delivery": "none",
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "job-created"
        assert data["next_run_at"] == next_run.isoformat()
        assert data["max_runs"] is None
        added_job = mock_db_session.add.call_args.args[0]
        assert added_job.persona_id == 7
        assert added_job.name == "Morning status"
        mock_db_session.commit.assert_awaited_once()

    def test_updates_persona_automation_and_disables_next_run(self, api_client, mock_db_session):
        persona = _make_persona(id=7)
        job = PersonaScheduledJob(
            id="job-2",
            persona_id=7,
            name="Daily sync",
            schedule_type="every",
            schedule_value="86400000",
            schedule_timezone="UTC",
            payload_type="agent_turn",
            payload_message="Daily sync",
            delivery="none",
            enabled=True,
            last_run_at=datetime(2026, 4, 14, 9, 0, tzinfo=UTC),
            next_run_at=datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
            run_count=4,
            max_runs=None,
            created_at=datetime(2026, 4, 10, 9, 0, tzinfo=UTC),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_db_session.execute.return_value = mock_result

        with (
            patch("app.api.persona.automations.get_or_create_persona", new=AsyncMock(return_value=persona)),
            patch("app.api.persona.automations.compute_next_run", return_value=datetime(2026, 4, 16, 9, 0, tzinfo=UTC)),
        ):
            response = api_client.patch(
                "/api/persona/automations/job-2",
                json={
                    "name": "Daily sync report",
                    "enabled": False,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Daily sync report"
        assert data["enabled"] is False
        assert data["next_run_at"] is None

    def test_deletes_persona_automation(self, api_client, mock_db_session):
        persona = _make_persona(id=7)
        job = PersonaScheduledJob(
            id="job-3",
            persona_id=7,
            name="Cleanup report",
            schedule_type="cron",
            schedule_value="0 2 * * *",
            schedule_timezone="UTC",
            payload_type="agent_turn",
            payload_message="Cleanup report",
            delivery="none",
            enabled=True,
            created_at=datetime(2026, 4, 10, 9, 0, tzinfo=UTC),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_db_session.execute.return_value = mock_result

        with patch("app.api.persona.automations.get_or_create_persona", new=AsyncMock(return_value=persona)):
            response = api_client.delete("/api/persona/automations/job-3")

        assert response.status_code == 204
        mock_db_session.delete.assert_awaited_once_with(job)
        mock_db_session.commit.assert_awaited_once()

    def test_triggers_persona_automation_and_returns_session_id(self, api_client, mock_db_session):
        persona = _make_persona(id=7)
        job = PersonaScheduledJob(
            id="job-4",
            persona_id=7,
            name="Immediate status",
            schedule_type="every",
            schedule_value="3600000",
            schedule_timezone="UTC",
            payload_type="agent_turn",
            payload_message="Post status back into persona workspace.",
            delivery="none",
            enabled=True,
            run_count=2,
            created_at=datetime(2026, 4, 10, 9, 0, tzinfo=UTC),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_db_session.execute.return_value = mock_result

        with (
            patch("app.api.persona.automations.get_or_create_persona", new=AsyncMock(return_value=persona)),
            patch(
                "app.api.persona.automations.execute_job",
                new=AsyncMock(return_value=MagicMock(output="Triggered", session_id="sess-123")),
            ),
            patch(
                "app.api.persona.automations.compute_next_run",
                return_value=datetime(2026, 4, 16, 9, 0, tzinfo=UTC),
            ),
        ):
            response = api_client.post("/api/persona/automations/job-4/trigger")

        assert response.status_code == 200
        data = response.json()
        assert data["output"] == "Triggered"
        assert data["session_id"] == "sess-123"
        assert data["job"]["run_count"] == 3
        assert data["job"]["next_run_at"] == "2026-04-16T09:00:00+00:00"
        mock_db_session.commit.assert_awaited_once()
