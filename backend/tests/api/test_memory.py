"""Tests for memory API endpoints."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import memory as memory_module
from app.main import app


@pytest.fixture
def mock_memory_service():
    """Create a mock memory service."""
    mock = AsyncMock()
    mock.delete_episode = AsyncMock(return_value=True)
    mock.bulk_delete = AsyncMock(return_value={"deleted": 0, "failed": 0, "errors": []})
    return mock


@pytest.fixture
async def client(mock_memory_service):
    """Async test client with dependency override."""

    def override_get_memory_svc(group_id: str = "default"):
        return mock_memory_service

    app.dependency_overrides[memory_module.get_memory_svc] = override_get_memory_svc

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


class TestDeleteEpisodeEndpoint:
    """Tests for DELETE /api/memory/episode/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_episode_success(
        self, client: AsyncClient, mock_memory_service: AsyncMock
    ):
        """Successful deletion returns 200 with success response."""
        mock_memory_service.delete_episode = AsyncMock(return_value=True)

        response = await client.delete(
            "/api/memory/episode/test-uuid-123",
            headers={"x-group-id": "test-group"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["episode_id"] == "test-uuid-123"
        assert "deleted" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_episode_not_found(
        self, client: AsyncClient, mock_memory_service: AsyncMock
    ):
        """Episode not found returns 404."""
        mock_memory_service.delete_episode = AsyncMock(side_effect=ValueError("Episode not found"))

        response = await client.delete("/api/memory/episode/nonexistent-uuid")

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_episode_server_error(
        self, client: AsyncClient, mock_memory_service: AsyncMock
    ):
        """Internal error returns 500."""
        mock_memory_service.delete_episode = AsyncMock(
            side_effect=RuntimeError("Neo4j connection failed")
        )

        response = await client.delete("/api/memory/episode/test-uuid")

        assert response.status_code == 500
        data = response.json()
        assert "failed" in data["detail"].lower()


class TestBulkDeleteEndpoint:
    """Tests for POST /api/memory/bulk-delete endpoint."""

    @pytest.mark.asyncio
    async def test_bulk_delete_success(self, client: AsyncClient, mock_memory_service: AsyncMock):
        """Successful bulk deletion returns success count."""
        mock_memory_service.bulk_delete = AsyncMock(
            return_value={"deleted": 3, "failed": 0, "errors": []}
        )

        response = await client.post(
            "/api/memory/bulk-delete",
            json={"ids": ["uuid-1", "uuid-2", "uuid-3"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 3
        assert data["failed"] == 0

    @pytest.mark.asyncio
    async def test_bulk_delete_partial_failure(
        self, client: AsyncClient, mock_memory_service: AsyncMock
    ):
        """Partial failure returns both success and failure counts."""
        mock_memory_service.bulk_delete = AsyncMock(
            return_value={
                "deleted": 2,
                "failed": 1,
                "errors": [{"id": "uuid-3", "error": "Not found"}],
            }
        )

        response = await client.post(
            "/api/memory/bulk-delete",
            json={"ids": ["uuid-1", "uuid-2", "uuid-3"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 2
        assert data["failed"] == 1
        assert len(data["errors"]) == 1

    @pytest.mark.asyncio
    async def test_bulk_delete_empty_list(self, client: AsyncClient):
        """Empty ID list returns validation error."""
        response = await client.post(
            "/api/memory/bulk-delete",
            json={"ids": []},
        )

        # Should return 422 for validation error (empty list)
        assert response.status_code == 422
