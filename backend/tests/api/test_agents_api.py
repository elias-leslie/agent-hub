"""Tests for Agent API endpoints.

Tests cover:
- Agent CRUD endpoints
- Metrics endpoints
- Error handling
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_service import AgentDTO


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
        "primary_model_id": "claude-sonnet-4-5",
        "fallback_models": ["gemini-3-flash"],
        "escalation_model_id": None,
        "strategies": {},
        "mandate_tags": ["coding"],
        "temperature": 0.7,
        "max_tokens": None,
        "is_active": True,
        "version": 1,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return AgentDTO(id=id, slug=slug, name=name, **defaults)


class TestAgentListEndpoint:
    """Tests for GET /api/agents endpoint."""

    @pytest.mark.asyncio
    async def test_list_agents_returns_200(self, test_client):
        """Test listing agents returns 200."""
        mock_dto = make_mock_dto()

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.list_agents = AsyncMock(return_value=[mock_dto])
            mock_get_service.return_value = mock_svc

            response = test_client.get("/api/agents")

            assert response.status_code == 200
            data = response.json()
            assert "agents" in data
            assert len(data["agents"]) == 1
            assert data["agents"][0]["slug"] == "coder"

    @pytest.mark.asyncio
    async def test_list_agents_with_inactive_filter(self, test_client):
        """Test listing agents with active_only=false."""
        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.list_agents = AsyncMock(return_value=[])
            mock_get_service.return_value = mock_svc

            response = test_client.get("/api/agents?active_only=false")

            assert response.status_code == 200
            mock_svc.list_agents.assert_called_once()


class TestAgentDetailEndpoint:
    """Tests for GET /api/agents/{slug} endpoint."""

    @pytest.mark.asyncio
    async def test_get_agent_returns_200(self, test_client):
        """Test getting specific agent returns 200."""
        mock_dto = make_mock_dto(system_prompt="You are a coder.")

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            response = test_client.get("/api/agents/coder")

            assert response.status_code == 200
            data = response.json()
            assert data["slug"] == "coder"
            assert data["name"] == "Code Generator"

    @pytest.mark.asyncio
    async def test_get_agent_returns_404_for_missing(self, test_client):
        """Test getting missing agent returns 404."""
        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=None)
            mock_get_service.return_value = mock_svc

            response = test_client.get("/api/agents/nonexistent")

            assert response.status_code == 404


class TestAgentCreateEndpoint:
    """Tests for POST /api/agents endpoint."""

    @pytest.mark.asyncio
    async def test_create_agent_returns_201(self, test_client):
        """Test creating agent returns 201."""
        mock_dto = make_mock_dto(slug="new-agent", name="New Agent")

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=None)
            mock_svc.create = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            response = test_client.post(
                "/api/agents",
                json={
                    "slug": "new-agent",
                    "name": "New Agent",
                    "system_prompt": "You are new.",
                    "primary_model_id": "claude-sonnet-4-5",
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert data["slug"] == "new-agent"

    @pytest.mark.asyncio
    async def test_create_agent_returns_409_for_duplicate(self, test_client):
        """Test creating duplicate agent returns 409."""
        mock_dto = make_mock_dto(slug="existing")

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            response = test_client.post(
                "/api/agents",
                json={
                    "slug": "existing",
                    "name": "Existing Agent",
                    "system_prompt": "You exist.",
                    "primary_model_id": "claude-sonnet-4-5",
                },
            )

            assert response.status_code == 409


class TestAgentUpdateEndpoint:
    """Tests for PUT /api/agents/{slug} endpoint."""

    @pytest.mark.asyncio
    async def test_update_agent_returns_200(self, test_client):
        """Test updating agent returns 200."""
        mock_dto = make_mock_dto()
        updated_dto = make_mock_dto(name="Updated Coder", version=2)

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_svc.update = AsyncMock(return_value=updated_dto)
            mock_get_service.return_value = mock_svc

            response = test_client.put(
                "/api/agents/coder",
                json={"name": "Updated Coder"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "Updated Coder"
            assert data["version"] == 2


class TestAgentDeleteEndpoint:
    """Tests for DELETE /api/agents/{slug} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_agent_returns_204(self, test_client):
        """Test soft deleting agent returns 204."""
        mock_dto = make_mock_dto()

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_svc.delete = AsyncMock(return_value=True)
            mock_get_service.return_value = mock_svc

            response = test_client.delete("/api/agents/coder")

            assert response.status_code == 204


class TestAgentMetricsEndpoint:
    """Tests for agent metrics endpoints."""

    @pytest.mark.asyncio
    async def test_get_all_metrics_returns_200(self, test_client):
        """Test getting all agent metrics."""
        mock_dto = make_mock_dto()

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.list_agents = AsyncMock(return_value=[mock_dto])
            mock_get_service.return_value = mock_svc

            response = test_client.get("/api/agents/metrics/all")

            assert response.status_code == 200
            data = response.json()
            assert "metrics" in data

    @pytest.mark.asyncio
    async def test_get_agent_metrics_returns_200(self, test_client):
        """Test getting specific agent metrics."""
        mock_dto = make_mock_dto()

        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=mock_dto)
            mock_get_service.return_value = mock_svc

            response = test_client.get("/api/agents/coder/metrics")

            assert response.status_code == 200
            data = response.json()
            assert data["slug"] == "coder"

    @pytest.mark.asyncio
    async def test_get_agent_metrics_returns_404_for_missing(self, test_client):
        """Test getting metrics for missing agent returns 404."""
        with patch("app.api.agents.get_agent_service") as mock_get_service:
            mock_svc = MagicMock()
            mock_svc.get_by_slug = AsyncMock(return_value=None)
            mock_get_service.return_value = mock_svc

            response = test_client.get("/api/agents/nonexistent/metrics")

            assert response.status_code == 404


class TestAgentVersionsEndpoint:
    """Tests for agent version history endpoint."""

    @pytest.mark.asyncio
    async def test_get_versions_returns_200(self, test_client):
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

            response = test_client.get("/api/agents/coder/versions")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["version"] == 2
