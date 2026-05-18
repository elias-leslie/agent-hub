"""Tests for Agent API endpoints.

Tests cover:
- Agent CRUD endpoints
- Metrics endpoints
- Error handling
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.models import GEMINI_FLASH, KIMI_CODE_FOR_CODING
from app.services.agent_service import AgentDTO
from app.services.memory.settings import MemorySettingsDTO


# Helper to create mock AgentDTO
def make_mock_dto(
    id: int = 1,
    slug: str = "coder",
    name: str = "Code Generator",
    **kwargs,
) -> AgentDTO:
    """Create a mock AgentDTO for testing."""
    defaults = {
        "description": "Generates code",
        "system_prompt": "You are a coder.",
        "primary_model_id": KIMI_CODE_FOR_CODING,
        "fallback_models": [GEMINI_FLASH],
        "escalation_model_id": None,
        "strategies": {},
        "temperature": 0.7,
        "thinking_level": "low",
        "verbosity_level": None,
        "is_active": True,
        "is_coding_agent": False,
        "memory_config": None,
        "max_concurrency": None,
        "max_subagent_concurrency": None,
        "daily_token_budget": None,
        "hourly_request_limit": None,
        "version": 1,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return AgentDTO(id=id, slug=slug, name=name, **defaults)


@pytest.fixture(autouse=True)
def _mock_memory_settings() -> Iterator[MemorySettingsDTO]:
    settings = MemorySettingsDTO(
        enabled=True,
        budget_enabled=True,
        total_budget=3500,
        continuity_enabled=True,
        continuity_max_sessions=5,
    )
    with patch(
        "app.api.agents.get_memory_settings",
        new=AsyncMock(return_value=settings),
    ):
        yield settings


class TestAgentListEndpoint:
    """Tests for GET /api/agents endpoint."""

    @pytest.mark.asyncio
    async def test_list_agents_returns_200(self, api_client):
        """Test listing agents returns 200."""
        mock_dto = make_mock_dto()

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.list_agents = AsyncMock(return_value=[mock_dto])
            mock_get_service.return_value = mock_svc

            response = api_client.get("/api/agents")

            assert response.status_code == 200
            data = response.json()
            assert "agents" in data
            assert len(data["agents"]) == 1
            assert data["agents"][0]["slug"] == "coder"
            assert data["agents"][0]["effective_memory_config"]["injection_enabled"] is True

    @pytest.mark.asyncio
    async def test_list_agents_with_inactive_filter(self, api_client):
        """Test listing agents with active_only=false."""
        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.list_agents = AsyncMock(return_value=[])
            mock_get_service.return_value = mock_svc

            response = api_client.get("/api/agents?active_only=false")

            assert response.status_code == 200
            mock_svc.list_agents.assert_called_once()


class TestAgentDetailEndpoint:
    """Tests for GET /api/agents/{slug} endpoint."""

    @pytest.mark.asyncio
    async def test_get_agent_returns_200(self, api_client):
        """Test getting specific agent returns 200."""
        mock_dto = make_mock_dto(system_prompt="You are a coder.")

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            response = api_client.get("/api/agents/coder")

            assert response.status_code == 200
            data = response.json()
            assert data["slug"] == "coder"
            assert data["name"] == "Code Generator"
            assert data["effective_memory_config"]["continuity_max_sessions"] == 5
            mock_svc.get_by_slug.assert_awaited_once()
            get_by_slug_args = mock_svc.get_by_slug.await_args
            assert get_by_slug_args is not None
            assert get_by_slug_args.kwargs["active_only"] is False

    @pytest.mark.asyncio
    async def test_get_agent_normalizes_sparse_memory_config_in_response(self, api_client):
        """Agent API should return canonical memory config shapes."""
        mock_dto = make_mock_dto(
            system_prompt="You are a coder.",
            memory_config={
                "injection_enabled": False,
                "include_mandates": True,
            },
        )

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            response = api_client.get("/api/agents/coder")

            assert response.status_code == 200
            data = response.json()
            assert data["memory_config"] == {
                "injection_enabled": False,
                "project_index_enabled": True,
                "tool_capabilities_enabled": True,
                "include_mandates": False,
                "include_guardrails": False,
                "include_references": False,
                "reference_index_enabled": False,
                "continuity_enabled": False,
                "continuity_max_sessions": 5,
                "audience_tags": [],
                "exclude_tags": [],
                "exclude_memory_uuids": [],
            }
            assert data["effective_memory_config"] == data["memory_config"]

    @pytest.mark.asyncio
    async def test_get_agent_returns_404_for_missing(self, api_client):
        """Test getting missing agent returns 404."""
        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=None)
            mock_get_service.return_value = mock_svc

            response = api_client.get("/api/agents/nonexistent")

            assert response.status_code == 404


class TestAgentCreateEndpoint:
    """Tests for POST /api/agents endpoint."""

    @pytest.mark.asyncio
    async def test_create_agent_returns_201(self, api_client):
        """Test creating agent returns 201."""
        mock_dto = make_mock_dto(slug="new-agent", name="New Agent")

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=None)
            mock_svc.create = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            response = api_client.post(
                "/api/agents",
                json={
                    "slug": "new-agent",
                    "name": "New Agent",
                    "system_prompt": "You are new.",
                    "primary_model_id": KIMI_CODE_FOR_CODING,
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert data["slug"] == "new-agent"
            mock_svc.create.assert_called_once()
            create_args = mock_svc.create.await_args
            assert create_args is not None
            create_kwargs = create_args.kwargs
            assert create_kwargs["thinking_level"] is None
            assert create_kwargs["verbosity_level"] is None

    @pytest.mark.asyncio
    async def test_create_agent_forwards_new_parameter_fields(self, api_client):
        """Test creating agent forwards thinking/verbosity and related params."""
        mock_dto = make_mock_dto(
            slug="new-agent",
            name="New Agent",
            thinking_level="xhigh",
            verbosity_level="high",
        )

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=None)
            mock_svc.create = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            response = api_client.post(
                "/api/agents",
                json={
                    "slug": "new-agent",
                    "name": "New Agent",
                    "system_prompt": "You are new.",
                    "primary_model_id": KIMI_CODE_FOR_CODING,
                    "thinking_level": "xhigh",
                    "verbosity_level": "high",
                },
            )

            assert response.status_code == 201
            create_args = mock_svc.create.await_args
            assert create_args is not None
            create_kwargs = create_args.kwargs
            assert create_kwargs["thinking_level"] == "xhigh"
            assert create_kwargs["verbosity_level"] == "high"

    @pytest.mark.asyncio
    async def test_create_agent_forwards_typed_memory_config(self, api_client):
        """Typed memory config payloads should arrive at service as plain dicts."""
        mock_dto = make_mock_dto(slug="router", name="Router")

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=None)
            mock_svc.create = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            response = api_client.post(
                "/api/agents",
                json={
                    "slug": "router",
                    "name": "Router",
                    "system_prompt": "You route context.",
                    "primary_model_id": KIMI_CODE_FOR_CODING,
                    "memory_config": {
                        "runtime_consumer_profile": "agent_operator",
                        "preview_consumer_profile": "agent_operator",
                        "exclude_memory_uuids": ["deadbeef"],
                    },
                },
            )

            assert response.status_code == 201
            create_args = mock_svc.create.await_args
            assert create_args is not None
            assert create_args.kwargs["memory_config"] == {
                "runtime_consumer_profile": "agent_operator",
                "preview_consumer_profile": "agent_operator",
                "exclude_memory_uuids": ["deadbeef"],
            }

    @pytest.mark.asyncio
    async def test_create_agent_returns_409_for_duplicate(self, api_client):
        """Test creating duplicate agent returns 409."""
        mock_dto = make_mock_dto(slug="existing")

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            response = api_client.post(
                "/api/agents",
                json={
                    "slug": "existing",
                    "name": "Existing Agent",
                    "system_prompt": "You exist.",
                    "primary_model_id": KIMI_CODE_FOR_CODING,
                },
            )

            assert response.status_code == 409


class TestAgentUpdateEndpoint:
    """Tests for PUT /api/agents/{slug} endpoint."""

    @pytest.mark.asyncio
    async def test_update_agent_returns_200(self, api_client):
        """Test updating agent returns 200."""
        mock_dto = make_mock_dto()
        updated_dto = make_mock_dto(name="Updated Coder", version=2)

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_svc.update = AsyncMock(return_value=updated_dto)
            mock_get_service.return_value = mock_svc

            response = api_client.put(
                "/api/agents/coder",
                json={"name": "Updated Coder"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "Updated Coder"
            assert data["version"] == 2
            get_by_slug_args = mock_svc.get_by_slug.await_args
            assert get_by_slug_args is not None
            assert get_by_slug_args.kwargs["active_only"] is False

    @pytest.mark.asyncio
    async def test_update_agent_forwards_new_parameter_fields(self, api_client):
        """Test updating agent forwards thinking/verbosity and related params."""
        mock_dto = make_mock_dto()
        updated_dto = make_mock_dto(
            thinking_level="high",
            verbosity_level="medium",
            version=2,
        )

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_svc.update = AsyncMock(return_value=updated_dto)
            mock_get_service.return_value = mock_svc

            response = api_client.put(
                "/api/agents/coder",
                json={
                    "thinking_level": "high",
                    "verbosity_level": "medium",
                },
            )

            assert response.status_code == 200
            update_args = mock_svc.update.await_args
            assert update_args is not None
            update_kwargs = update_args.kwargs
            assert update_kwargs["thinking_level"] == "high"
            assert update_kwargs["verbosity_level"] == "medium"

    @pytest.mark.asyncio
    async def test_update_agent_returns_404_when_service_update_returns_none(self, api_client):
        """Test missing agent during update returns 404 instead of being masked as 500."""
        mock_dto = make_mock_dto()

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_svc.update = AsyncMock(return_value=None)
            mock_get_service.return_value = mock_svc

            response = api_client.put(
                "/api/agents/coder",
                json={"name": "Updated Coder"},
            )

            assert response.status_code == 404


class TestAgentDeleteEndpoint:
    """Tests for DELETE /api/agents/{slug} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_agent_returns_204(self, api_client):
        """Test soft deleting agent returns 204."""
        mock_dto = make_mock_dto()

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_svc.delete = AsyncMock(return_value=True)
            mock_get_service.return_value = mock_svc

            response = api_client.delete("/api/agents/coder")

            assert response.status_code == 204


class TestAgentMetricsEndpoint:
    """Tests for agent metrics endpoints."""

    @pytest.mark.asyncio
    async def test_get_all_metrics_returns_200(self, api_client):
        """Test getting all agent metrics."""
        mock_dto = make_mock_dto()

        with (
            patch("app.api.agents.get_agent_service") as mock_get_service,
            patch("app.api.agents.compute_agent_metrics") as mock_compute_metrics,
        ):
            mock_svc = MagicMock()
            mock_svc.list_agents = AsyncMock(return_value=[mock_dto])
            mock_get_service.return_value = mock_svc

            # Mock metrics response
            mock_compute_metrics.return_value = {
                "slug": "coder",
                "name": "Code Generator",
                "total_sessions": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
            }

            response = api_client.get("/api/agents/metrics/all")

            assert response.status_code == 200
            data = response.json()
            assert "metrics" in data

    @pytest.mark.asyncio
    async def test_get_agent_metrics_returns_200(self, api_client):
        """Test getting specific agent metrics."""
        mock_dto = make_mock_dto()

        with (
            patch("app.api.agents.get_agent_service") as mock_get_service,
            patch("app.api.agents.compute_agent_metrics") as mock_compute_metrics,
        ):
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            # Mock metrics response
            mock_compute_metrics.return_value = {
                "slug": "coder",
                "name": "Code Generator",
                "total_sessions": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
            }

            response = api_client.get("/api/agents/coder/metrics")

            assert response.status_code == 200
            data = response.json()
            assert data["slug"] == "coder"

    @pytest.mark.asyncio
    async def test_get_agent_metrics_returns_404_for_missing(self, api_client):
        """Test getting metrics for missing agent returns 404."""
        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=None)
            mock_get_service.return_value = mock_svc

            response = api_client.get("/api/agents/nonexistent/metrics")

            assert response.status_code == 404


class TestAgentActivityEndpoint:
    """Tests for agent runtime activity endpoint."""

    @pytest.mark.asyncio
    async def test_get_agent_activity_returns_compact_runtime_evidence(self, api_client, mock_db_session):
        """Activity endpoint exposes sessions and request logs without raw DB reads."""
        mock_dto = make_mock_dto()
        session_row = SimpleNamespace(
            id="session-1",
            project_id="summitflow",
            external_id="task-1",
            model="kimi-code/kimi-for-coding",
            status="completed",
            created_at=datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
            updated_at=datetime(2026, 5, 14, 12, 3, tzinfo=UTC),
            models_used=["kimi-code/kimi-for-coding"],
            providers_used=["kimi-code"],
            health_detail=None,
            summary_outcome="completed",
            current_branch="main",
        )
        request_row = SimpleNamespace(
            created_at=datetime(2026, 5, 14, 12, 1, tzinfo=UTC),
            model="kimi-code/kimi-for-coding",
            status_code=200,
            latency_ms=1234,
            tokens_in=100,
            tokens_out=200,
            timed_out=False,
            used_fallback=False,
            fallback_model=None,
            session_id="session-1",
        )
        session_result = MagicMock()
        session_result.scalars.return_value.all.return_value = [session_row]
        request_result = MagicMock()
        request_result.scalars.return_value.all.return_value = [request_row]
        mock_db_session.execute = AsyncMock(side_effect=[session_result, request_result])

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            response = api_client.get("/api/agents/coder/activity?external_id=task-1&limit=5")

        assert response.status_code == 200
        data = response.json()
        assert data["agent_slug"] == "coder"
        assert data["sessions"][0]["id"] == "session-1"
        assert data["sessions"][0]["models_used"] == ["kimi-code/kimi-for-coding"]
        assert data["requests"][0]["status_code"] == 200
        assert data["requests"][0]["timed_out"] is False


class TestAgentBenchmarkDashboardEndpoint:
    """Tests for agent benchmark dashboard endpoint."""

    @pytest.mark.asyncio
    async def test_get_agent_benchmarks_returns_dashboard(self, api_client):
        """Test fetching persisted benchmark dashboard data."""
        mock_dto = make_mock_dto()
        dashboard = {
            "agent_slug": "coder",
            "overview": {
                "total_runs": 3,
                "avg_score": 94.2,
                "pass_rate": 75.0,
                "open_regressions": 2,
                "latest_completed_at": "2026-03-11T12:00:00Z",
                "tracked_models": ["codex/gpt-5.4", "claude-sonnet-4-6"],
            },
            "trend": [
                {
                    "run_id": "run-1",
                    "completed_at": "2026-03-11T12:00:00Z",
                    "suite_id": "persona-patience",
                    "run_kind": "benchmark",
                    "avg_score": 94.2,
                    "pass_rate": 75.0,
                    "attempts": 12,
                    "prompt_version": "2026-03-11T11:16:06Z:abcd1234",
                }
            ],
            "recent_runs": [
                {
                    "run_id": "run-1",
                    "benchmark_id": "persona-benchmark-aaaa1111",
                    "suite_id": "persona-patience",
                    "run_kind": "benchmark",
                    "started_at": "2026-03-11T11:40:00Z",
                    "completed_at": "2026-03-11T12:00:00Z",
                    "avg_score": 94.2,
                    "pass_rate": 75.0,
                    "attempt_count": 12,
                    "passed_attempt_count": 9,
                    "infra_failure_count": 0,
                    "models": ["codex/gpt-5.4"],
                    "case_ids": ["session_patience_quiet"],
                    "config_snapshot": {"thinking_level": "medium"},
                    "metadata": {},
                }
            ],
            "open_regressions": [
                {
                    "regression_key": "session_patience_quiet::wrong_fields: should_dispatch",
                    "suite_id": "persona-patience",
                    "case_id": "session_patience_quiet",
                    "failure_detail": "wrong_fields: should_dispatch",
                    "status": "open",
                    "occurrence_count": 2,
                    "latest_avg_score": 78.8,
                    "affected_models": ["codex/gpt-5.4"],
                    "opened_at": "2026-03-11T11:00:00Z",
                    "last_seen_at": "2026-03-11T12:00:00Z",
                    "resolved_at": None,
                }
            ],
            "model_performance": [
                {
                    "model_id": "codex/gpt-5.4",
                    "attempts": 12,
                    "avg_score": 94.2,
                    "pass_rate": 75.0,
                    "avg_latency_ms": 1200.0,
                    "avg_total_tokens": 1800.0,
                    "avg_turns": 4.2,
                    "avg_tool_calls": 2.3,
                    "latest_completed_at": "2026-03-11T12:00:00Z",
                }
            ],
            "suites": [
                {
                    "suite_id": "persona-patience",
                    "run_count": 3,
                    "avg_score": 94.2,
                    "pass_rate": 75.0,
                    "open_regressions": 2,
                    "latest_completed_at": "2026-03-11T12:00:00Z",
                    "tracked_models": ["codex/gpt-5.4", "claude-sonnet-4-6"],
                    "case_ids": ["session_patience_quiet"],
                    "run_kinds": ["benchmark"],
                }
            ],
            "cases": [
                {
                    "case_id": "session_patience_quiet",
                    "attempts": 12,
                    "pass_rate": 75.0,
                    "avg_score": 94.2,
                    "open_regressions": 2,
                    "latest_completed_at": "2026-03-11T12:00:00Z",
                    "latest_failure_detail": "wrong_fields: should_dispatch",
                    "tracked_models": ["codex/gpt-5.4"],
                    "suite_ids": ["persona-patience"],
                }
            ],
            "experiments": [
                {
                    "experiment_key": "persona-patience-ab",
                    "name": "Persona patience A/B",
                    "suite_id": "persona-patience",
                    "status": "open",
                    "decision": "hold",
                    "decision_reason": "underpowered",
                    "hypothesis": "Candidate harness should reduce false redispatches.",
                    "min_runs_per_cohort": 3,
                    "baseline": {
                        "label": "baseline",
                        "run_count": 2,
                        "avg_score": 94.0,
                        "avg_pass_rate": 75.0,
                        "avg_total_tokens": 1800.0,
                        "avg_turns": 4.0,
                        "avg_tool_calls": 2.0,
                        "config_fingerprints": ["abcd1234"],
                        "config_stable": True,
                        "prompt_versions": ["2026-03-11T11:16:06Z:abcd1234"],
                        "latest_completed_at": "2026-03-11T12:00:00Z",
                    },
                    "candidate": {
                        "label": "candidate",
                        "run_count": 1,
                        "avg_score": 95.0,
                        "avg_pass_rate": 83.3,
                        "avg_total_tokens": 1700.0,
                        "avg_turns": 3.8,
                        "avg_tool_calls": 1.8,
                        "config_fingerprints": ["efgh5678"],
                        "config_stable": True,
                        "prompt_versions": ["2026-03-11T11:20:00Z:efgh5678"],
                        "latest_completed_at": "2026-03-11T12:05:00Z",
                    },
                    "score_delta": {"mean_delta": 1.0, "ci_low": -2.0, "ci_high": 3.8},
                    "pass_rate_delta": {"mean_delta": 8.3, "ci_low": -16.7, "ci_high": 25.0},
                    "tool_call_delta": {"mean_delta": -0.2, "ci_low": -0.6, "ci_high": 0.1},
                    "updated_at": "2026-03-11T12:05:00Z",
                    "created_at": "2026-03-11T11:50:00Z",
                }
            ],
        }

        with (
            patch("app.api.agents.get_agent_service") as mock_get_service,
            patch("app.api.agents.get_agent_benchmark_dashboard") as mock_get_dashboard,
        ):
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc
            mock_get_dashboard.return_value = dashboard

            response = api_client.get("/api/agents/coder/benchmarks?days=14&limit=10")

            assert response.status_code == 200
            data = response.json()
            assert data["agent_slug"] == "coder"
            assert data["overview"]["total_runs"] == 3
            assert data["suites"][0]["suite_id"] == "persona-patience"
            assert data["cases"][0]["case_id"] == "session_patience_quiet"
            assert data["open_regressions"][0]["case_id"] == "session_patience_quiet"
            assert data["experiments"][0]["experiment_key"] == "persona-patience-ab"
            mock_get_dashboard.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_agent_benchmarks_returns_404_for_missing(self, api_client):
        """Test fetching benchmark dashboard for missing agent."""
        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=None)
            mock_get_service.return_value = mock_svc

            response = api_client.get("/api/agents/nonexistent/benchmarks")

            assert response.status_code == 404


class TestAgentBenchmarkRunDetailEndpoint:
    """Tests for individual benchmark run drill-down endpoint."""

    @pytest.mark.asyncio
    async def test_get_benchmark_run_detail_returns_attempts(self, api_client):
        """Test fetching a single benchmark run with its attempts."""
        mock_dto = make_mock_dto()
        from app.api.schemas.agent_schemas import AgentBenchmarkRunDetail

        run_detail = AgentBenchmarkRunDetail(
            run_id="run-1",
            benchmark_id="persona-benchmark-aaaa1111",
            suite_id="persona-patience",
            run_kind="benchmark",
            started_at="2026-03-11T11:40:00Z",
            completed_at="2026-03-11T12:00:00Z",
            avg_score=94.2,
            pass_rate=75.0,
            attempt_count=2,
            passed_attempt_count=1,
            infra_failure_count=0,
            models=["codex/gpt-5.4"],
            case_ids=["session_patience_quiet"],
            attempts=[
                {
                    "id": "att-1",
                    "model_id": "codex/gpt-5.4",
                    "case_id": "session_patience_quiet",
                    "case_name": "Quiet Session Patience",
                    "run_number": 1,
                    "passed": True,
                    "composite_score": 100.0,
                    "correctness_score": 1.0,
                    "primary_action": "wait",
                    "confidence": "high",
                    "summary": "Session is healthy, waiting.",
                    "latency_ms": 2400,
                    "total_tokens": 1500,
                },
                {
                    "id": "att-2",
                    "model_id": "codex/gpt-5.4",
                    "case_id": "session_patience_quiet",
                    "case_name": "Quiet Session Patience",
                    "run_number": 2,
                    "passed": False,
                    "composite_score": 85.0,
                    "correctness_score": 0.75,
                    "primary_action": "reconcile",
                    "confidence": "medium",
                    "summary": "Session seems stalled.",
                    "failure_kind": "model",
                    "failure_detail": "wrong_fields: primary_action",
                    "latency_ms": 3200,
                    "total_tokens": 1800,
                },
            ],
        )

        with (
            patch("app.api.agents.get_agent_service") as mock_get_service,
            patch("app.api.agents.get_agent_benchmark_run") as mock_get_run,
        ):
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc
            mock_get_run.return_value = run_detail

            response = api_client.get("/api/agents/coder/benchmarks/run-1")

            assert response.status_code == 200
            data = response.json()
            assert data["run_id"] == "run-1"
            assert len(data["attempts"]) == 2
            assert data["attempts"][0]["passed"] is True
            assert data["attempts"][0]["case_name"] == "Quiet Session Patience"
            assert data["attempts"][1]["failure_detail"] == "wrong_fields: primary_action"
            mock_get_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_benchmark_run_detail_returns_404_for_missing_run(self, api_client):
        """Test 404 when benchmark run doesn't exist."""
        mock_dto = make_mock_dto()

        with (
            patch("app.api.agents.get_agent_service") as mock_get_service,
            patch("app.api.agents.get_agent_benchmark_run") as mock_get_run,
        ):
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc
            mock_get_run.return_value = None

            response = api_client.get("/api/agents/coder/benchmarks/nonexistent")

            assert response.status_code == 404


class TestAgentVersionsEndpoint:
    """Tests for agent version history endpoint."""

    @pytest.mark.asyncio
    async def test_get_versions_returns_200(self, api_client):
        """Test getting version history."""
        mock_dto = make_mock_dto()
        mock_versions = [
            {"version": 2, "changed_by": "user", "change_reason": "Updated"},
            {"version": 1, "changed_by": "system", "change_reason": "Created"},
        ]

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_svc.get_version_history = AsyncMock(return_value=mock_versions)
            mock_get_service.return_value = mock_svc

            response = api_client.get("/api/agents/coder/versions")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["version"] == 2
