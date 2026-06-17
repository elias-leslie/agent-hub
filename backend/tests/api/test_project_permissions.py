"""Tests for project permissions API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
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
    daily_cost_budget_usd: float | None = None,
    monthly_cost_budget_usd: float | None = None,
    budget_alert_threshold: float = 0.8,
) -> MagicMock:
    perm = MagicMock(spec=ProjectPermission)
    perm.project_id = project_id
    perm.permission_tier = tier
    perm.auto_exec_enabled = auto_exec
    perm.execution_start_hour = start_hour
    perm.execution_end_hour = end_hour
    perm.root_path = root_path
    perm.daily_cost_budget_usd = daily_cost_budget_usd
    perm.monthly_cost_budget_usd = monthly_cost_budget_usd
    perm.budget_alert_threshold = budget_alert_threshold
    perm.updated_at = datetime.now(UTC)
    perm.created_at = datetime.now(UTC)
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
        perms = [_make_perm("proj-a", "read"), _make_perm("proj-b", "full")]
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
            assert data[1]["permission_tier"] == "full"

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
# GET /api/projects/roots
# ---------------------------------------------------------------------------


class TestListProjectRoots:
    @pytest.mark.asyncio
    async def test_returns_canonical_project_roots(self, client):
        ac, _ = client
        with patch(
            "app.api.project_permissions.get_known_roots",
            return_value={"agent-hub": "/srv/workspaces/projects/agent-hub"},
        ):
            resp = await ac.get("/api/projects/roots")
            assert resp.status_code == 200
            assert resp.json() == {"agent-hub": "/srv/workspaces/projects/agent-hub"}


# ---------------------------------------------------------------------------
# GET /api/projects/catalog
# ---------------------------------------------------------------------------


class TestListProjectCatalog:
    @pytest.mark.asyncio
    async def test_catalog_includes_memory_only_project_scopes(self, client):
        ac, _ = client
        perms = [
            _make_perm(
                "agent-hub",
                "full",
                root_path="/srv/workspaces/projects/agent-hub",
            )
        ]
        with (
            patch(
                "app.api.project_permissions.list_project_permissions",
                new_callable=AsyncMock,
                return_value=perms,
            ),
            patch(
                "app.api.project_permissions.get_known_roots",
                return_value={"agent-hub": "/srv/workspaces/projects/agent-hub"},
            ),
            patch(
                "app.api.project_permissions._list_memory_project_ids",
                new_callable=AsyncMock,
                return_value={"agent-hub", "the-aftertimes"},
            ),
        ):
            resp = await ac.get("/api/projects/catalog")

        assert resp.status_code == 200
        data = {item["project_id"]: item for item in resp.json()}
        assert data["agent-hub"]["has_permission"] is True
        assert data["agent-hub"]["has_root"] is True
        assert data["agent-hub"]["has_memory"] is True
        assert data["the-aftertimes"]["label"] == "the aftertimes"
        assert data["the-aftertimes"]["has_permission"] is False
        assert data["the-aftertimes"]["has_root"] is False
        assert data["the-aftertimes"]["has_memory"] is True


# ---------------------------------------------------------------------------
# POST /api/projects/permissions
# ---------------------------------------------------------------------------


class TestCreatePermission:
    @pytest.mark.asyncio
    async def test_creates_permission(self, client):
        ac, _ = client
        created = _make_perm("test2", "full", True, 0, 24, "/srv/workspaces/projects/test2")
        with patch(
            "app.api.project_permissions.create_project_permission",
            new_callable=AsyncMock,
            return_value=created,
        ):
            resp = await ac.post(
                "/api/projects/permissions",
                json={
                    "project_id": "test2",
                    "permission_tier": "full",
                    "auto_exec_enabled": True,
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["project_id"] == "test2"
            assert data["permission_tier"] == "full"
            assert data["auto_exec_enabled"] is True

    @pytest.mark.asyncio
    async def test_rejects_invalid_tier(self, client):
        ac, _ = client
        resp = await ac.post(
            "/api/projects/permissions",
            json={"project_id": "test2", "permission_tier": "invalid"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_returns_409_for_duplicate_project(self, client):
        ac, _ = client
        with patch(
            "app.api.project_permissions.create_project_permission",
            new_callable=AsyncMock,
            side_effect=ValueError("Project permission already exists for 'test2'"),
        ):
            resp = await ac.post(
                "/api/projects/permissions",
                json={"project_id": "test2"},
            )
            assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/permissions
# ---------------------------------------------------------------------------


class TestGetPermission:
    @pytest.mark.asyncio
    async def test_returns_permission_for_existing_project(self, client):
        ac, _ = client
        perm = _make_perm("summitflow", "write", True, 9, 17, "/home/testuser/summitflow")
        with patch(
            "app.api.project_permissions.get_project_permission",
            new_callable=AsyncMock,
            return_value=perm,
        ):
            resp = await ac.get("/api/projects/summitflow/permissions")
            assert resp.status_code == 200
            data = resp.json()
            assert data["project_id"] == "summitflow"
            assert data["permission_tier"] == "full"
            assert data["auto_exec_enabled"] is True
            assert data["execution_start_hour"] == 9
            assert data["execution_end_hour"] == 17
            assert data["root_path"] == "/home/testuser/summitflow"

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
# DELETE /api/projects/{project_id}/permissions
# ---------------------------------------------------------------------------


class TestDeletePermission:
    @pytest.mark.asyncio
    async def test_deletes_permission(self, client):
        ac, _ = client
        deleted = _make_perm("proj", "full")
        with patch(
            "app.api.project_permissions.delete_project_permission",
            new_callable=AsyncMock,
            return_value=deleted,
        ):
            resp = await ac.delete("/api/projects/proj/permissions")
            assert resp.status_code == 204
            assert resp.text == ""

    @pytest.mark.asyncio
    async def test_returns_404_for_missing_project(self, client):
        ac, _ = client
        with patch(
            "app.api.project_permissions.delete_project_permission",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await ac.delete("/api/projects/missing/permissions")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/projects/{project_id}/permissions
# ---------------------------------------------------------------------------


class TestUpdatePermission:
    @pytest.mark.asyncio
    async def test_updates_tier(self, client):
        ac, _ = client
        updated = _make_perm("proj", "full")
        with patch(
            "app.api.project_permissions.update_project_permission",
            new_callable=AsyncMock,
            return_value=updated,
        ):
            resp = await ac.patch(
                "/api/projects/proj/permissions",
                json={"permission_tier": "full"},
            )
            assert resp.status_code == 200
            assert resp.json()["permission_tier"] == "full"

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
                json={"permission_tier": "full"},
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
            permission_tier="full",
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
            assert data["permission_tier"] == "full"
            assert data["reason"] == "allowed"

    @pytest.mark.asyncio
    async def test_returns_denied_when_auto_exec_off(self, client):
        ac, _ = client
        result = ExecutionPermissionResult(
            allowed=False,
            permission_tier="full",
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


# ---------------------------------------------------------------------------
# PATCH /api/projects/{project_id}/permissions — budget fields
# ---------------------------------------------------------------------------


class TestUpdatePermissionBudget:
    @pytest.mark.asyncio
    async def test_update_daily_budget(self, client):
        """Test updating daily cost budget via PATCH."""
        ac, _ = client
        updated = _make_perm("proj", "full", daily_cost_budget_usd=25.0)
        with (
            patch(
                "app.api.project_permissions.update_project_permission",
                new_callable=AsyncMock,
                return_value=updated,
            ),
            patch(
                "app.services.project_budget.invalidate_budget_cache",
                new_callable=AsyncMock,
            ) as mock_invalidate,
        ):
            resp = await ac.patch(
                "/api/projects/proj/permissions",
                json={"daily_cost_budget_usd": 25.0},
            )
            assert resp.status_code == 200
            assert resp.json()["daily_cost_budget_usd"] == 25.0
            # Budget cache should be invalidated when budget fields change
            mock_invalidate.assert_called_once_with("proj")

    @pytest.mark.asyncio
    async def test_update_monthly_budget(self, client):
        """Test updating monthly cost budget via PATCH."""
        ac, _ = client
        updated = _make_perm("proj", "full", monthly_cost_budget_usd=500.0)
        with (
            patch(
                "app.api.project_permissions.update_project_permission",
                new_callable=AsyncMock,
                return_value=updated,
            ),
            patch(
                "app.services.project_budget.invalidate_budget_cache",
                new_callable=AsyncMock,
            ) as mock_invalidate,
        ):
            resp = await ac.patch(
                "/api/projects/proj/permissions",
                json={"monthly_cost_budget_usd": 500.0},
            )
            assert resp.status_code == 200
            assert resp.json()["monthly_cost_budget_usd"] == 500.0
            mock_invalidate.assert_called_once_with("proj")

    @pytest.mark.asyncio
    async def test_update_budget_alert_threshold(self, client):
        """Test updating budget alert threshold via PATCH."""
        ac, _ = client
        updated = _make_perm("proj", "full", budget_alert_threshold=0.9)
        with (
            patch(
                "app.api.project_permissions.update_project_permission",
                new_callable=AsyncMock,
                return_value=updated,
            ),
            patch(
                "app.services.project_budget.invalidate_budget_cache",
                new_callable=AsyncMock,
            ) as mock_invalidate,
        ):
            resp = await ac.patch(
                "/api/projects/proj/permissions",
                json={"budget_alert_threshold": 0.9},
            )
            assert resp.status_code == 200
            assert resp.json()["budget_alert_threshold"] == 0.9
            mock_invalidate.assert_called_once_with("proj")

    @pytest.mark.asyncio
    async def test_update_non_budget_field_does_not_invalidate_cache(self, client):
        """Test that updating non-budget fields does not invalidate budget cache."""
        ac, _ = client
        updated = _make_perm("proj", "full")
        with (
            patch(
                "app.api.project_permissions.update_project_permission",
                new_callable=AsyncMock,
                return_value=updated,
            ),
            patch(
                "app.services.project_budget.invalidate_budget_cache",
                new_callable=AsyncMock,
            ) as mock_invalidate,
        ):
            resp = await ac.patch(
                "/api/projects/proj/permissions",
                json={"permission_tier": "full"},
            )
            assert resp.status_code == 200
            mock_invalidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_permission_response_includes_budget_fields(self, client):
        """Test that permission response includes all budget fields."""
        ac, _ = client
        perm = _make_perm(
            "proj",
            "full",
            daily_cost_budget_usd=10.0,
            monthly_cost_budget_usd=100.0,
            budget_alert_threshold=0.85,
        )
        with patch(
            "app.api.project_permissions.get_project_permission",
            new_callable=AsyncMock,
            return_value=perm,
        ):
            resp = await ac.get("/api/projects/proj/permissions")
            assert resp.status_code == 200
            data = resp.json()
            assert data["daily_cost_budget_usd"] == 10.0
            assert data["monthly_cost_budget_usd"] == 100.0
            assert data["budget_alert_threshold"] == 0.85


# ---------------------------------------------------------------------------
# GET /api/projects/{project_id}/budget
# ---------------------------------------------------------------------------


class TestGetProjectBudget:
    @pytest.mark.asyncio
    async def test_get_budget_returns_usage(self, client):
        """Test GET /projects/{id}/budget returns budget usage data."""
        ac, _ = client
        budget_data = {
            "project_id": "test-proj",
            "daily": {"used": 3.5, "limit": 10.0, "remaining": 6.5},
            "monthly": {"used": 45.0, "limit": 100.0, "remaining": 55.0},
            "alert_level": None,
        }
        with patch(
            "app.services.project_budget.get_project_budget_usage",
            new_callable=AsyncMock,
            return_value=budget_data,
        ):
            resp = await ac.get("/api/projects/test-proj/budget")
            assert resp.status_code == 200
            data = resp.json()
            assert data["project_id"] == "test-proj"
            assert data["daily"]["used"] == 3.5
            assert data["daily"]["limit"] == 10.0
            assert data["daily"]["remaining"] == 6.5
            assert data["monthly"]["used"] == 45.0
            assert data["monthly"]["limit"] == 100.0
            assert data["monthly"]["remaining"] == 55.0
            assert data["alert_level"] is None

    @pytest.mark.asyncio
    async def test_get_budget_unlimited_project(self, client):
        """Test GET /projects/{id}/budget for project with no limits."""
        ac, _ = client
        budget_data = {
            "project_id": "unlimited-proj",
            "daily": {"used": 10.0, "limit": None, "remaining": None},
            "monthly": {"used": 50.0, "limit": None, "remaining": None},
            "alert_level": None,
        }
        with patch(
            "app.services.project_budget.get_project_budget_usage",
            new_callable=AsyncMock,
            return_value=budget_data,
        ):
            resp = await ac.get("/api/projects/unlimited-proj/budget")
            assert resp.status_code == 200
            data = resp.json()
            assert data["daily"]["limit"] is None
            assert data["daily"]["remaining"] is None
            assert data["monthly"]["limit"] is None

    @pytest.mark.asyncio
    async def test_get_budget_with_warning_alert(self, client):
        """Test GET /projects/{id}/budget returns warning alert level."""
        ac, _ = client
        budget_data = {
            "project_id": "warn-proj",
            "daily": {"used": 8.5, "limit": 10.0, "remaining": 1.5},
            "monthly": {"used": 50.0, "limit": 100.0, "remaining": 50.0},
            "alert_level": "warning",
        }
        with patch(
            "app.services.project_budget.get_project_budget_usage",
            new_callable=AsyncMock,
            return_value=budget_data,
        ):
            resp = await ac.get("/api/projects/warn-proj/budget")
            assert resp.status_code == 200
            data = resp.json()
            assert data["alert_level"] == "warning"


# ---------------------------------------------------------------------------
# GET /api/projects/budgets
# ---------------------------------------------------------------------------


class TestGetAllProjectBudgets:
    @pytest.mark.asyncio
    async def test_get_all_budgets_returns_list(self, client):
        """Test GET /projects/budgets returns budget overview for all projects."""
        ac, _ = client
        perms = [_make_perm("proj-a"), _make_perm("proj-b")]
        budget_a = {
            "project_id": "proj-a",
            "daily": {"used": 1.0, "limit": 10.0, "remaining": 9.0},
            "monthly": {"used": 20.0, "limit": 100.0, "remaining": 80.0},
            "alert_level": None,
        }
        budget_b = {
            "project_id": "proj-b",
            "daily": {"used": 9.5, "limit": 10.0, "remaining": 0.5},
            "monthly": {"used": 95.0, "limit": 100.0, "remaining": 5.0},
            "alert_level": "critical",
        }

        with (
            patch(
                "app.api.project_permissions.list_project_permissions",
                new_callable=AsyncMock,
                return_value=perms,
            ),
            patch(
                "app.services.project_budget.get_project_budget_usage",
                new_callable=AsyncMock,
                side_effect=[budget_a, budget_b],
            ),
        ):
            resp = await ac.get("/api/projects/budgets")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            assert data[0]["project_id"] == "proj-a"
            assert data[0]["alert_level"] is None
            assert data[1]["project_id"] == "proj-b"
            assert data[1]["alert_level"] == "critical"

    @pytest.mark.asyncio
    async def test_get_all_budgets_empty_when_no_projects(self, client):
        """Test GET /projects/budgets returns empty list when no projects."""
        ac, _ = client
        with patch(
            "app.api.project_permissions.list_project_permissions",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = await ac.get("/api/projects/budgets")
            assert resp.status_code == 200
            data = resp.json()
            assert data == []
