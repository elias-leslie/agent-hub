"""Tests for memory API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    """Async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


class TestDeleteEpisodeEndpoint:
    """Tests for DELETE /api/memory/episode/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_episode_success(self, client: AsyncClient):
        """Successful deletion returns 200 with success response."""
        with patch("app.api.memory.get_memory_svc") as mock_get_svc:
            mock_service = AsyncMock()
            mock_service.delete_episode = AsyncMock(return_value=True)
            mock_get_svc.return_value = mock_service

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
    async def test_delete_episode_not_found(self, client: AsyncClient):
        """Episode not found returns 404."""
        with patch("app.api.memory.get_memory_svc") as mock_get_svc:
            mock_service = AsyncMock()
            mock_service.delete_episode = AsyncMock(side_effect=ValueError("Episode not found"))
            mock_get_svc.return_value = mock_service

            response = await client.delete("/api/memory/episode/nonexistent-uuid")

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_episode_server_error(self, client: AsyncClient):
        """Internal error returns 500."""
        with patch("app.api.memory.get_memory_svc") as mock_get_svc:
            mock_service = AsyncMock()
            mock_service.delete_episode = AsyncMock(
                side_effect=RuntimeError("Neo4j connection failed")
            )
            mock_get_svc.return_value = mock_service

            response = await client.delete("/api/memory/episode/test-uuid")

            assert response.status_code == 500
            data = response.json()
            assert "failed" in data["detail"].lower()


class TestBulkDeleteEndpoint:
    """Tests for POST /api/memory/bulk-delete endpoint."""

    @pytest.mark.asyncio
    async def test_bulk_delete_success(self, client: AsyncClient):
        """Successful bulk deletion returns success count."""
        with patch("app.api.memory.get_memory_svc") as mock_get_svc:
            mock_service = AsyncMock()
            mock_service.bulk_delete = AsyncMock(
                return_value={"deleted": 3, "failed": 0, "errors": []}
            )
            mock_get_svc.return_value = mock_service

            response = await client.post(
                "/api/memory/bulk-delete",
                json={"ids": ["uuid-1", "uuid-2", "uuid-3"]},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["deleted"] == 3
            assert data["failed"] == 0

    @pytest.mark.asyncio
    async def test_bulk_delete_partial_failure(self, client: AsyncClient):
        """Partial failure returns both success and failure counts."""
        with patch("app.api.memory.get_memory_svc") as mock_get_svc:
            mock_service = AsyncMock()
            mock_service.bulk_delete = AsyncMock(
                return_value={
                    "deleted": 2,
                    "failed": 1,
                    "errors": [{"id": "uuid-3", "error": "Not found"}],
                }
            )
            mock_get_svc.return_value = mock_service

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
