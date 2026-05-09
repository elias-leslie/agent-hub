"""Tests for memory API endpoints."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import memory as memory_module
from app.main import app
from tests.conftest import TEST_HEADERS


@pytest.fixture
def mock_memory_service():
    """Create a mock memory service."""
    mock = AsyncMock()
    mock.delete_episode = AsyncMock(return_value=True)
    mock.bulk_delete = AsyncMock(return_value={"deleted": 0, "failed": 0, "errors": []})
    return mock


@pytest.fixture
async def client(mock_memory_service):
    """Async test client with dependency override and source headers."""
    from unittest.mock import patch

    def override_get_memory_svc(scope_params=None):
        return mock_memory_service

    app.dependency_overrides[memory_module.get_memory_svc] = override_get_memory_svc

    # Also patch get_memory_service for bulk ops that call it directly (imported inside functions)
    with patch("app.services.memory.get_memory_service", return_value=mock_memory_service):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=TEST_HEADERS,  # Add test headers for kill switch compliance
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
            "/api/memory/episode/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            headers={"x-memory-scope": "global"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["episode_id"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert "deleted" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_episode_not_found(
        self, client: AsyncClient, mock_memory_service: AsyncMock
    ):
        """Episode not found returns 404."""
        mock_memory_service.delete_episode = AsyncMock(side_effect=ValueError("Episode not found"))

        response = await client.delete("/api/memory/episode/deadbeef")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_episode_server_error(
        self, client: AsyncClient, mock_memory_service: AsyncMock
    ):
        """Internal error returns 500."""
        mock_memory_service.delete_episode = AsyncMock(
            side_effect=RuntimeError("Database connection failed")
        )

        response = await client.delete(
            "/api/memory/episode/c3d4e5f6-0000-4000-8000-000000000000"
        )

        assert response.status_code == 500
        data = response.json()
        assert "failed" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_episode_forwards_change_reason(
        self, client: AsyncClient, mock_memory_service: AsyncMock
    ):
        mock_memory_service.delete_episode = AsyncMock(return_value=True)

        response = await client.delete(
            "/api/memory/episode/a1b2c3d4-e5f6-7890-abcd-ef1234567890?change_reason=dedupe",
        )

        assert response.status_code == 200
        mock_memory_service.delete_episode.assert_awaited_once_with(
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            changed_by="api",
            change_reason="dedupe",
        )


class TestUpdateEpisodeEndpoint:
    """Tests for PATCH /api/memory/episode/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_update_episode_content_keeps_uuid(
        self, client: AsyncClient
    ):
        """Content updates should patch in place and preserve UUID."""
        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
        mock_repo = AsyncMock()
        mock_repo.get_as_dict = AsyncMock(return_value={"injection_tier": "reference"})
        mock_repo.update = AsyncMock(return_value=True)

        with (
            patch("app.services.memory.embedder.get_embedder", return_value=mock_embedder),
            patch("app.api.memory_episodes_handlers.get_memory_repository", return_value=mock_repo),
        ):
            response = await client.patch(
                "/api/memory/episode/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                json={"content": "**Episode Refresh**: Use refreshed episode content."},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["episode_id"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert "content" in data["message"].lower()
        mock_embedder.embed.assert_awaited_once_with("**Episode Refresh**: Use refreshed episode content.")
        mock_repo.update.assert_awaited_once()
        update_call = mock_repo.update.await_args
        assert update_call is not None
        update_kwargs = update_call.kwargs
        assert update_kwargs["metadata"]["compact_content"] == (
            "**Episode Refresh**: Use refreshed episode content."
        )
        assert update_kwargs["metadata"]["compact_status"] == "source_ready"
        assert update_kwargs["metadata"]["source_quality_method"] == "format_standard"

    @pytest.mark.asyncio
    async def test_update_episode_tier_only(
        self, client: AsyncClient
    ):
        """Tier-only updates should not require re-embedding."""
        mock_repo = AsyncMock()
        mock_repo.update = AsyncMock(return_value=True)

        with patch("app.api.memory_episodes_handlers.get_memory_repository", return_value=mock_repo):
            response = await client.patch(
                "/api/memory/episode/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                json={"injection_tier": "mandate"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["injection_tier"] == "mandate"
        mock_repo.update.assert_awaited_once_with(
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            injection_tier="mandate",
            changed_by="api",
        )

    @pytest.mark.asyncio
    async def test_update_episode_forwards_change_reason(
        self, client: AsyncClient
    ):
        mock_repo = AsyncMock()
        mock_repo.update = AsyncMock(return_value=True)
        mock_repo.get_as_dict = AsyncMock(return_value={"version": 4})

        with patch("app.api.memory_episodes_handlers.get_memory_repository", return_value=mock_repo):
            response = await client.patch(
                "/api/memory/episode/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                json={"injection_tier": "mandate", "change_reason": "normalize tier"},
            )

        assert response.status_code == 200
        assert response.json()["version"] == 4
        mock_repo.update.assert_awaited_once_with(
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            changed_by="api",
            injection_tier="mandate",
            change_reason="normalize tier",
        )

    @pytest.mark.asyncio
    async def test_update_episode_rejects_invalid_content_for_existing_tier(
        self, client: AsyncClient
    ):
        """Content-only updates should still enforce the topic-header format."""
        mock_repo = AsyncMock()
        mock_repo.get_as_dict = AsyncMock(return_value={"injection_tier": "mandate"})

        with patch("app.api.memory_episodes_handlers.get_memory_repository", return_value=mock_repo):
            response = await client.patch(
                "/api/memory/episode/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                json={"content": "**Git Safety**: Git commits should use commit.sh in Agent Hub sessions."},
            )

        assert response.status_code == 422
        body = response.json()
        assert "direct imperative" in body["message"].lower()
        assert body["error"] == "validation_error"

    @pytest.mark.asyncio
    async def test_update_episode_requires_fields(self, client: AsyncClient):
        """Empty payload should be rejected clearly."""
        response = await client.patch(
            "/api/memory/episode/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            json={},
        )

        assert response.status_code == 400
        assert "No fields to update" in response.json()["message"]


class TestSaveLearningEndpoint:
    """Tests for POST /api/memory/save-learning endpoint."""

    @pytest.mark.asyncio
    async def test_save_learning_validation_uses_message_and_hint(self, client: AsyncClient):
        """Invalid learning format should return normalized validation payload."""
        response = await client.post(
            "/api/memory/save-learning",
            json={
                "content": "Use commit.sh --push --msg \"description\" for new commits. Use commit.sh --current --push for clean ahead branches.",
                "summary": "Use commit flow",
                "injection_tier": "mandate",
            },
        )

        assert response.status_code == 422
        body = response.json()
        assert body["error"] == "validation_error"
        assert "bold topic header" in body["message"].lower()
        assert "FORMAT_STANDARD" in body["hint"]

    @pytest.mark.asyncio
    async def test_save_learning_persists_context_routing_fields(self, client: AsyncClient):
        """Valid save-learning requests should persist routing metadata on the created memory."""
        creator = SimpleNamespace(
            create=AsyncMock(
                return_value=SimpleNamespace(
                    success=True,
                    uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    validation_error=None,
                )
            )
        )

        with (
            patch("app.api.memory_agent_learning_saver.check_duplicate", new=AsyncMock(return_value=None)),
            patch("app.services.memory.episode_creator.get_episode_creator", return_value=creator),
            patch("app.api.memory_agent_learning_saver.set_episode_properties", new=AsyncMock()) as mock_set_properties,
        ):
            response = await client.post(
                "/api/memory/save-learning",
                json={
                    "content": "**Reference Targeting**: Use applicability rules to scope reference memories to the agents that need them.",
                    "summary": "Scope references",
                    "injection_tier": "reference",
                    "pinned": True,
                    "trigger_task_types": ["backend"],
                    "trigger_phases": ["implementation", "verification"],
                    "context_kind": "capability",
                    "applicability": {
                        "consumer_profiles": ["codex_startup"],
                        "exclude_consumer_profiles": ["agent_runtime"],
                        "agent_slugs": ["persona"],
                        "exclude_agent_slugs": ["formatter"],
                        "audience_tags": ["operator-tooling"],
                        "exclude_audience_tags": ["narrow-output"],
                    },
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["uuid"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        mock_set_properties.assert_awaited_once_with(
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            True,
            ["backend"],
            ["implementation", "verification"],
            "capability",
            {
                "consumer_profiles": ["codex_startup"],
                "exclude_consumer_profiles": ["agent_runtime"],
                "agent_slugs": ["persona"],
                "exclude_agent_slugs": ["formatter"],
                "audience_tags": ["operator-tooling"],
                "exclude_audience_tags": ["narrow-output"],
            },
            change_reason="Learning properties updated",
            render_mode=None,
        )


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
            json={"ids": [
                "a1b2c3d4-0000-4000-8000-000000000001",
                "a1b2c3d4-0000-4000-8000-000000000002",
                "a1b2c3d4-0000-4000-8000-000000000003",
            ]},
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
                "errors": [{"id": "a1b2c3d4-0000-4000-8000-000000000003", "error": "Not found"}],
            }
        )

        response = await client.post(
            "/api/memory/bulk-delete",
            json={"ids": [
                "a1b2c3d4-0000-4000-8000-000000000001",
                "a1b2c3d4-0000-4000-8000-000000000002",
                "a1b2c3d4-0000-4000-8000-000000000003",
            ]},
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


class TestMemoryRevisionEndpoints:
    @pytest.mark.asyncio
    async def test_list_memory_revisions_returns_history(self, client: AsyncClient):
        with patch(
            "app.api.memory_episodes.handle_list_episode_revisions",
            new=AsyncMock(
                return_value={
                    "revisions": [
                        {
                            "id": "d4e5f6a7",
                            "memory_uuid": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
                            "version": 3,
                            "action": "update",
                            "content": "**Topic**: Use dt.",
                            "summary": "use dt",
                            "injection_tier": "reference",
                            "scope": "global",
                            "tags": [],
                            "content_hash": "abcd1234",
                            "created_at": "2026-03-12T13:00:00Z",
                        }
                    ],
                    "total": 1,
                }
            ),
        ):
            response = await client.get("/api/memory/episode/c3d4e5f6/revisions")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["revisions"][0]["id"] == "d4e5f6a7"

    @pytest.mark.asyncio
    async def test_restore_memory_revision_returns_restored_episode(self, client: AsyncClient):
        with patch(
            "app.api.memory_episodes.handle_restore_episode_revision",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "episode_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
                    "injection_tier": "reference",
                    "message": "Restored revision d4e5f6a7",
                    "version": 5,
                }
            ),
        ):
            response = await client.post(
                "/api/memory/episode/c3d4e5f6/revisions/d4e5f6a7/restore",
                json={"change_reason": "Rollback bad edit"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["version"] == 5
