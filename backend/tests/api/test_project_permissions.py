"""Tests for project permissions API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models.project_permission import ProjectPermission
from app.services.project_permission_service import ExecutionPermissionResult

# ---------------------------------------------------------------------------
# Test headers (bypass access control middleware)
# ---------------------------------------------------------------------------

TEST_HEADERS = {
    "X-Agent-Hub-Internal": "agent-hub-internal-v1",
    "X-Source-Client": "pytest",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_perm(
    project_id: str = "test-project",
    tier: str = "read",
    auto_exec: bool = False,
    start_hour: int = 0,
    end_hour: int = 24,
    root_path: str | None = None,
) -> MagicMock:
    perm = MagicMock(spec=ProjectPermission)
    perm.project_id = project_id
    perm.permission_tier = tier
    perm.auto_exec_enabled = auto_exec
    perm.execution_start_hour = start_hour
    perm.execution_end_hour = end_hour
    perm.root_path = root_path
    perm.updated_at = datetime.now(timezone.utc)
    perm.created_at = datetime.now(timezone.utc)
    return perm


@pytest.fixture
async def client():
    mock_db = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=TEST_HEADERS,
    ) as ac:
        yield ac, mock_db
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/projects/permissions
# ---------------------------------------------------------------------------


class TestListPermissions:
    @pytest.mark.asyncio
    async def test_list_returns_all_permissions(self, client):
        ac, _ = client
        perms = [_make_perm("proj-a", "read"), _make_perm("proj-b", "yolo")]
        with patch(
            "app.api.project_permissions.list_project_permissions",
            new_callable=AsyncMock,
            return_value=perms,
        ):
            resp = await ac.get("/api/projects/permissions")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            assert data[0]["project_id"] == "proj-a"
            assert data[1]["permission_tier"] == "yolo"

    @pytest.mark.asyncio
    async def test_list_returns_empty_when_no_permissions(self, client):
        ac, _ = client
        with patch(
            "app.api.project_permissions.list_project_permissions",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await ac.get("/api/projects/permissions")
            assert resp.status_code == 200
            assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/permissions
# ---------------------------------------------------------------------------


class TestGetPermission:
    @pytest.mark.asyncio
    async def test_returns_permission_for_existing_project(self, client):
        ac, _ = client
        perm = _make_perm("summitflow", "write", True, 9, 17, "/home/kasadis/summitflow")
        with patch(
            "app.api.project_permissions.get_project_permission",
            new_callable=AsyncMock,
            return_value=perm,
        ):
            resp = await ac.get("/api/projects/summitflow/permissions")
            assert resp.status_code == 200
            data = resp.json()
            assert data["project_id"] == "summitflow"
            assert data["permission_tier"] == "write"
            assert data["auto_exec_enabled"] is True
            assert data["execution_start_hour"] == 9
            assert data["execution_end_hour"] == 17
            assert data["root_path"] == "/home/kasadis/summitflow"

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_project(self, client):
        ac, _ = client
        with patch(
            "app.api.project_permissions.get_project_permission",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await ac.get("/api/projects/nonexistent/permissions")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/projects/{project_id}/permissions
# ---------------------------------------------------------------------------


class TestUpdatePermission:
    @pytest.mark.asyncio
    async def test_updates_tier(self, client):
        ac, _ = client
        updated = _make_perm("proj", "yolo")
        with patch(
            "app.api.project_permissions.update_project_permission",
            new_callable=AsyncMock,
            return_value=updated,
        ):
            resp = await ac.patch(
                "/api/projects/proj/permissions",
                json={"permission_tier": "yolo"},
            )
            assert resp.status_code == 200
            assert resp.json()["permission_tier"] == "yolo"

    @pytest.mark.asyncio
    async def test_rejects_invalid_tier(self, client):
        ac, _ = client
        resp = await ac.patch(
            "/api/projects/proj/permissions",
            json={"permission_tier": "invalid"},
        )
        assert resp.status_code == 400
        body = resp.json()
        # FastAPI may return detail as string or structured error
        body_str = str(body)
        assert "invalid" in body_str.lower() or "tier" in body_str.lower()

    @pytest.mark.asyncio
    async def test_rejects_same_start_and_end_hour(self, client):
        ac, _ = client
        resp = await ac.patch(
            "/api/projects/proj/permissions",
            json={"execution_start_hour": 10, "execution_end_hour": 10},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_returns_404_for_missing_project(self, client):
        ac, _ = client
        with patch(
            "app.api.project_permissions.update_project_permission",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await ac.patch(
                "/api/projects/nonexistent/permissions",
                json={"permission_tier": "write"},
            )
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/execution-permission
# ---------------------------------------------------------------------------


class TestExecutionPermission:
    @pytest.mark.asyncio
    async def test_returns_allowed_when_permitted(self, client):
        ac, _ = client
        result = ExecutionPermissionResult(
            allowed=True,
            permission_tier="yolo",
            auto_exec_enabled=True,
            in_time_window=True,
            reason="allowed",
        )
        with patch(
            "app.api.project_permissions.check_execution_permission",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = await ac.get("/api/projects/proj/execution-permission")
            assert resp.status_code == 200
            data = resp.json()
            assert data["allowed"] is True
            assert data["permission_tier"] == "yolo"
            assert data["reason"] == "allowed"

    @pytest.mark.asyncio
    async def test_returns_denied_when_auto_exec_off(self, client):
        ac, _ = client
        result = ExecutionPermissionResult(
            allowed=False,
            permission_tier="write",
            auto_exec_enabled=False,
            in_time_window=True,
            reason="auto_exec_disabled",
        )
        with patch(
            "app.api.project_permissions.check_execution_permission",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = await ac.get("/api/projects/proj/execution-permission")
            assert resp.status_code == 200
            data = resp.json()
            assert data["allowed"] is False
            assert data["reason"] == "auto_exec_disabled"

    @pytest.mark.asyncio
    async def test_returns_denied_for_unknown_project(self, client):
        ac, _ = client
        result = ExecutionPermissionResult(
            allowed=False,
            permission_tier="unknown",
            auto_exec_enabled=False,
            in_time_window=False,
            reason="project_not_found",
        )
        with patch(
            "app.api.project_permissions.check_execution_permission",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = await ac.get("/api/projects/unknown/execution-permission")
            assert resp.status_code == 200
            data = resp.json()
            assert data["allowed"] is False
