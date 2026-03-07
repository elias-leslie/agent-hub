"""Tests for ownership inventory API endpoints."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.db import get_db
from app.main import app
from app.services.ownership_inventory import OwnershipOwner
from tests.conftest import APITestClient


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock async database session."""
    return AsyncMock()


def _owner(**overrides: object) -> OwnershipOwner:
    now = datetime(2026, 3, 7, 18, 0, tzinfo=UTC)
    payload: dict[str, object] = {
        "task_id": "task-12345678",
        "session_id": "sess-1",
        "agent_slug": "codex",
        "branch": "task-12345678/main",
        "worktree_path": "/tmp/worktree",
        "is_worktree": True,
        "session_status": "active",
        "workstream_status": "authoritative",
        "workstream_note": "Current owner",
        "ownership_kind": "scoped",
        "scope_paths": ["backend/app/services/tools/catalog.py"],
        "updated_at": now,
        "created_at": now,
        "age_minutes": 12,
        "is_stale": False,
    }
    payload.update(overrides)
    return OwnershipOwner(**payload)


@pytest.fixture
def client(mock_session: AsyncMock) -> Generator[APITestClient]:
    async def override_get_db() -> AsyncGenerator[AsyncMock]:
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield APITestClient(app)
    finally:
        app.dependency_overrides.clear()


class TestProjectOwnership:
    """Tests for GET /api/ownership/projects/{project_id}/live."""

    def test_live_project_ownership_returns_normalized_rows(
        self, client: APITestClient
    ) -> None:
        with (
            patch(
                "app.api.ownership.query_project_ownership",
                new=AsyncMock(
                    return_value=[
                        _owner(),
                        _owner(
                            session_id="sess-2",
                            task_id=None,
                            ownership_kind="unscoped",
                            scope_paths=[],
                            workstream_status=None,
                            workstream_note=None,
                        ),
                    ]
                ),
            ),
        ):
            response = client.get("/api/ownership/projects/agent-hub/live")

        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == "agent-hub"
        assert "generated_at" in data
        assert len(data["active_owners"]) == 2
        assert data["active_owners"][0]["task_id"] == "task-12345678"
        assert data["active_owners"][0]["is_worktree"] is True
        assert data["active_owners"][0]["ownership_kind"] == "scoped"
        assert data["active_owners"][0]["scope_paths"] == [
            "backend/app/services/tools/catalog.py"
        ]
        assert data["active_owners"][1]["ownership_kind"] == "unscoped"
        assert data["active_owners"][1]["scope_paths"] == []

    def test_live_project_ownership_propagates_empty_inventory(
        self, client: APITestClient
    ) -> None:
        with (
            patch(
                "app.api.ownership.query_project_ownership",
                new=AsyncMock(return_value=[]),
            ),
        ):
            response = client.get("/api/ownership/projects/summitflow/live")

        assert response.status_code == 200
        assert response.json()["active_owners"] == []
