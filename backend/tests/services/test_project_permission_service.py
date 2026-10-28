"""Tests for the project permission service: CRUD and SummitFlow client access sync."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.project_permission import ProjectPermission
from app.services.project_permission_service import (
    create_project_permission,
    delete_project_permission,
    get_project_permission,
    list_project_permissions,
    reconcile_registered_project_access,
    update_project_permission,
)


def _make_permission(
    project_id: str = "test-project",
    root_path: str | None = None,
) -> ProjectPermission:
    """Create a mock ProjectPermission object."""
    perm = MagicMock(spec=ProjectPermission)
    perm.project_id = project_id
    perm.root_path = root_path
    perm.updated_at = datetime.now(UTC)
    perm.created_at = datetime.now(UTC)
    return perm


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestGetProjectPermission:
    @pytest.mark.asyncio
    async def test_returns_permission_when_found(self):
        mock_perm = _make_permission("summitflow")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        result = await get_project_permission(mock_db, "summitflow")
        assert result is not None
        assert result.project_id == "summitflow"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await get_project_permission(mock_db, "nonexistent")
        assert result is None


class TestListProjectPermissions:
    @pytest.mark.asyncio
    async def test_returns_all_permissions(self):
        perms = [_make_permission("a"), _make_permission("b")]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = perms
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        result = await list_project_permissions(mock_db)
        assert len(result) == 2


class TestUpdateProjectPermission:
    @pytest.mark.asyncio
    async def test_updates_root_path_and_budget(self):
        mock_perm = _make_permission("proj")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        result = await update_project_permission(
            mock_db, "proj", root_path="/srv/proj", daily_cost_budget_usd=5.0
        )
        assert result is not None
        assert result.root_path == "/srv/proj"
        assert result.daily_cost_budget_usd == 5.0
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_project(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await update_project_permission(
            mock_db, "nonexistent", root_path="/srv/x"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_updates_registered_project_access_for_summitflow_clients(self):
        mock_perm = _make_permission("test2")
        summitflow_client = MagicMock()
        summitflow_client.id = "client-summitflow"
        summitflow_client.display_name = "SummitFlow"
        summitflow_client.allowed_projects = '["summitflow"]'
        backend_client = MagicMock()
        backend_client.id = "client-backend"
        backend_client.display_name = "summitflow-backend"
        backend_client.allowed_projects = '["summitflow","agent-hub"]'
        other_client = MagicMock()
        other_client.id = "client-other"
        other_client.display_name = "Portfolio AI"
        other_client.allowed_projects = '["portfolio-ai"]'

        permission_result = MagicMock()
        permission_result.scalar_one_or_none.return_value = mock_perm
        client_result = MagicMock()
        client_scalars = MagicMock()
        client_scalars.all.return_value = [summitflow_client, backend_client, other_client]
        client_result.scalars.return_value = client_scalars

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [permission_result, client_result]

        with (
            patch(
                "app.services.project_permission_service.invalidate_client_cache"
            ) as mock_invalidate_client_cache,
        ):
            result = await update_project_permission(
                mock_db, "test2", root_path="/srv/test2"
            )

        assert result is not None
        assert result.root_path == "/srv/test2"
        assert summitflow_client.allowed_projects == '["summitflow", "test2"]'
        assert backend_client.allowed_projects == '["summitflow", "agent-hub", "test2"]'
        assert other_client.allowed_projects == '["portfolio-ai"]'
        mock_invalidate_client_cache.assert_any_call("client-summitflow")
        mock_invalidate_client_cache.assert_any_call("client-backend")
        assert mock_invalidate_client_cache.call_count == 2


class TestCreateProjectPermission:
    @pytest.mark.asyncio
    async def test_creates_permission_and_resolves_default_root(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        created = {}

        def capture_add(perm):
            created["perm"] = perm

        mock_db.add = MagicMock(side_effect=capture_add)

        with (
            patch(
                "app.services.project_permission_service.aresolve_project_root",
                new_callable=AsyncMock,
                return_value=Path("/srv/workspaces/projects/test2"),
            ),
            patch("app.services.project_permission_service.invalidate_project_cache"),
        ):
            result = await create_project_permission(
                mock_db,
                "test2",
            )

        assert result is created["perm"]
        assert created["perm"].project_id == "test2"
        assert created["perm"].root_path == "/srv/workspaces/projects/test2"
        mock_db.commit.assert_awaited_once()
        mock_db.refresh.assert_awaited_once_with(created["perm"])

    @pytest.mark.asyncio
    async def test_rejects_duplicate_project(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = _make_permission("proj")
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="already exists"):
            await create_project_permission(mock_db, "proj")


class TestReconcileRegisteredProjectAccess:
    @pytest.mark.asyncio
    async def test_repairs_missing_registered_project_access(self):
        permissions = [
            _make_permission("agent-hub"),
            _make_permission("summitflow"),
            _make_permission("test1"),
            _make_permission("vantage"),
        ]
        summitflow_client = MagicMock()
        summitflow_client.id = "client-summitflow"
        summitflow_client.display_name = "SummitFlow"
        summitflow_client.allowed_projects = (
            '["summitflow","st-cli","agent-hub","test1"]'
        )
        backend_client = MagicMock()
        backend_client.id = "client-backend"
        backend_client.display_name = "summitflow-backend"
        backend_client.allowed_projects = '["summitflow","agent-hub"]'
        other_client = MagicMock()
        other_client.id = "client-other"
        other_client.display_name = "Portfolio AI"
        other_client.allowed_projects = '["portfolio-ai"]'

        permission_result = MagicMock()
        permission_scalars = MagicMock()
        permission_scalars.all.return_value = permissions
        permission_result.scalars.return_value = permission_scalars

        client_result = MagicMock()
        client_scalars = MagicMock()
        client_scalars.all.return_value = [summitflow_client, backend_client, other_client]
        client_result.scalars.return_value = client_scalars

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [permission_result, client_result]

        with patch("app.services.project_permission_service.invalidate_client_cache") as mock_invalidate:
            changed = await reconcile_registered_project_access(mock_db)

        assert changed == ["client-summitflow", "client-backend"]
        assert summitflow_client.allowed_projects == (
            '["summitflow", "st-cli", "agent-hub", "test1", "vantage"]'
        )
        assert backend_client.allowed_projects == '["summitflow", "agent-hub", "test1", "vantage"]'
        assert other_client.allowed_projects == '["portfolio-ai"]'
        mock_db.commit.assert_awaited_once()
        mock_invalidate.assert_any_call("client-summitflow")
        mock_invalidate.assert_any_call("client-backend")
        assert mock_invalidate.call_count == 2

    @pytest.mark.asyncio
    async def test_registered_projects_without_a_permission_row_are_allowed(self):
        # aico was registered in SummitFlow but never got a permission row, so the
        # SummitFlow client's hand-grown list lacked it and session upserts 403'd.
        permissions = [_make_permission("summitflow")]
        summitflow_client = MagicMock()
        summitflow_client.id = "client-summitflow"
        summitflow_client.display_name = "summitflow"
        summitflow_client.allowed_projects = '["summitflow"]'

        permission_result = MagicMock()
        permission_result.scalars.return_value.all.return_value = permissions
        client_result = MagicMock()
        client_result.scalars.return_value.all.return_value = [summitflow_client]
        mock_db = AsyncMock()
        mock_db.execute.side_effect = [permission_result, client_result]

        with patch("app.services.project_permission_service.invalidate_client_cache"):
            changed = await reconcile_registered_project_access(
                mock_db, ["summitflow", "aico", "tether"]
            )

        assert changed == ["client-summitflow"]
        assert summitflow_client.allowed_projects == '["summitflow", "aico", "tether"]'

    @pytest.mark.asyncio
    async def test_known_registry_trims_projects_summitflow_never_calls(self):
        # The list only ever grew: test fixtures, retired projects and permission rows
        # of unregistered projects stayed forever. A known registry is the whole list,
        # and every registered project is in it.
        permissions = [_make_permission("summitflow"), _make_permission("test1"),
                       _make_permission("neri")]
        summitflow_client = MagicMock()
        summitflow_client.id = "client-summitflow"
        summitflow_client.display_name = "summitflow"
        summitflow_client.allowed_projects = '["summitflow", "agent-hub", "test1", "fydor", "neri", "st-cli"]'

        permission_result = MagicMock()
        permission_result.scalars.return_value.all.return_value = permissions
        client_result = MagicMock()
        client_result.scalars.return_value.all.return_value = [summitflow_client]
        mock_db = AsyncMock()
        mock_db.execute.side_effect = [permission_result, client_result]

        with patch("app.services.project_permission_service.invalidate_client_cache"):
            changed = await reconcile_registered_project_access(mock_db, ["summitflow", "agent-hub", "neri"])

        assert changed == ["client-summitflow"]
        assert summitflow_client.allowed_projects == '["summitflow", "neri", "agent-hub"]'

    @pytest.mark.asyncio
    async def test_empty_registry_never_empties_the_list(self):
        summitflow_client = MagicMock()
        summitflow_client.id = "client-summitflow"
        summitflow_client.display_name = "summitflow"
        summitflow_client.allowed_projects = '["summitflow", "agent-hub"]'
        permission_result = MagicMock()
        permission_result.scalars.return_value.all.return_value = [_make_permission("summitflow")]
        client_result = MagicMock()
        client_result.scalars.return_value.all.return_value = [summitflow_client]
        mock_db = AsyncMock()
        mock_db.execute.side_effect = [permission_result, client_result]

        with patch("app.services.project_permission_service.invalidate_client_cache"):
            changed = await reconcile_registered_project_access(mock_db, [])

        assert changed == []
        assert summitflow_client.allowed_projects == '["summitflow", "agent-hub"]'

    @pytest.mark.asyncio
    async def test_noops_when_registered_access_is_aligned(self):
        permissions = [
            _make_permission("agent-hub"),
            _make_permission("summitflow"),
            _make_permission("test1"),
            _make_permission("vantage"),
        ]
        summitflow_client = MagicMock()
        summitflow_client.id = "client-summitflow"
        summitflow_client.display_name = "SummitFlow"
        summitflow_client.allowed_projects = (
            '["summitflow","st-cli","agent-hub","test1","vantage"]'
        )
        backend_client = MagicMock()
        backend_client.id = "client-backend"
        backend_client.display_name = "summitflow-backend"
        backend_client.allowed_projects = '["summitflow","agent-hub","test1","vantage"]'

        permission_result = MagicMock()
        permission_scalars = MagicMock()
        permission_scalars.all.return_value = permissions
        permission_result.scalars.return_value = permission_scalars

        client_result = MagicMock()
        client_scalars = MagicMock()
        client_scalars.all.return_value = [summitflow_client, backend_client]
        client_result.scalars.return_value = client_scalars

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [permission_result, client_result]

        with patch("app.services.project_permission_service.invalidate_client_cache") as mock_invalidate:
            changed = await reconcile_registered_project_access(mock_db)

        assert changed == []
        mock_db.commit.assert_not_awaited()
        mock_invalidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_permission_and_syncs_summitflow_clients(self):
        missing_permission_result = MagicMock()
        missing_permission_result.scalar_one_or_none.return_value = None
        summitflow_client = MagicMock()
        summitflow_client.id = "client-summitflow"
        summitflow_client.display_name = "SummitFlow"
        summitflow_client.allowed_projects = '["summitflow","agent-hub"]'
        backend_client = MagicMock()
        backend_client.id = "client-backend"
        backend_client.display_name = "summitflow-backend"
        backend_client.allowed_projects = '["summitflow"]'
        unrelated_client = MagicMock()
        unrelated_client.id = "client-other"
        unrelated_client.display_name = "Portfolio AI"
        unrelated_client.allowed_projects = '["portfolio-ai"]'
        client_result = MagicMock()
        client_scalars = MagicMock()
        client_scalars.all.return_value = [
            summitflow_client,
            backend_client,
            unrelated_client,
        ]
        client_result.scalars.return_value = client_scalars

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [missing_permission_result, client_result]
        created = {}

        def capture_add(perm):
            created["perm"] = perm

        mock_db.add = MagicMock(side_effect=capture_add)

        with (
            patch(
                "app.services.project_permission_service.aresolve_project_root",
                new_callable=AsyncMock,
                return_value=Path("/srv/workspaces/projects/test2"),
            ),
            patch(
                "app.services.project_permission_service.invalidate_client_cache"
            ) as mock_invalidate_client_cache,
            patch("app.services.project_permission_service.invalidate_project_cache"),
        ):
            result = await create_project_permission(
                mock_db,
                "test2",
            )

        assert result is created["perm"]
        assert summitflow_client.allowed_projects == '["summitflow", "agent-hub", "test2"]'
        assert backend_client.allowed_projects == '["summitflow", "test2"]'
        assert unrelated_client.allowed_projects == '["portfolio-ai"]'
        mock_invalidate_client_cache.assert_any_call("client-summitflow")
        mock_invalidate_client_cache.assert_any_call("client-backend")
        assert mock_invalidate_client_cache.call_count == 2


class TestDeleteProjectPermission:
    @pytest.mark.asyncio
    async def test_returns_none_for_missing_project(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await delete_project_permission(mock_db, "missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_removes_registered_project_access_for_summitflow_clients(self):
        mock_perm = _make_permission("test2")
        summitflow_client = MagicMock()
        summitflow_client.id = "client-summitflow"
        summitflow_client.display_name = "SummitFlow"
        summitflow_client.allowed_projects = '["summitflow", "test2"]'
        backend_client = MagicMock()
        backend_client.id = "client-backend"
        backend_client.display_name = "summitflow-backend"
        backend_client.allowed_projects = '["summitflow", "agent-hub", "test2"]'

        permission_result = MagicMock()
        permission_result.scalar_one_or_none.return_value = mock_perm
        client_result = MagicMock()
        client_scalars = MagicMock()
        client_scalars.all.return_value = [summitflow_client, backend_client]
        client_result.scalars.return_value = client_scalars

        mock_db = AsyncMock()
        mock_db.execute.side_effect = [permission_result, client_result]

        with (
            patch(
                "app.services.project_permission_service.invalidate_client_cache"
            ) as mock_invalidate_client_cache,
            patch("app.services.project_permission_service.invalidate_project_cache"),
        ):
            result = await delete_project_permission(mock_db, "test2")

        assert result is mock_perm
        assert summitflow_client.allowed_projects == '["summitflow"]'
        assert backend_client.allowed_projects == '["summitflow", "agent-hub"]'
        mock_db.delete.assert_awaited_once_with(mock_perm)
        mock_invalidate_client_cache.assert_any_call("client-summitflow")
        mock_invalidate_client_cache.assert_any_call("client-backend")
        assert mock_invalidate_client_cache.call_count == 2


class TestRegistryDrivenAccess:
    @pytest.mark.asyncio
    async def test_newly_registered_project_is_reconciled_without_restart(self, monkeypatch):
        from contextlib import asynccontextmanager

        from app.services import project_permission_service as service

        monkeypatch.setattr(service, "_reconciled_registry", None)
        registry = {"summitflow": "/p/summitflow"}
        reconcile = AsyncMock(return_value=["client-summitflow"])
        db = AsyncMock()

        @asynccontextmanager
        async def session():
            yield db

        with (
            patch("app.core.project_roots.get_registered_project_roots", AsyncMock(side_effect=lambda: dict(registry))),
            patch("app.db.async_session", session),
            patch.object(service, "reconcile_registered_project_access", reconcile),
        ):
            assert await service.reconcile_access_if_registry_changed() == ["client-summitflow"]
            assert await service.reconcile_access_if_registry_changed() == []
            registry["new-project"] = "/p/new-project"
            await service.reconcile_access_if_registry_changed()

        assert [call.args[1] for call in reconcile.await_args_list] == [
            ["summitflow"],
            ["new-project", "summitflow"],
        ]

    @pytest.mark.asyncio
    async def test_middleware_rereads_a_reconciled_summitflow_client(self):
        from app.middleware import access_control_handler_helpers as helpers

        stale = {"id": "c1", "display_name": "summitflow", "allowed_projects": '["summitflow"]'}
        fresh = {**stale, "allowed_projects": '["summitflow", "new-project"]'}
        other = {"id": "c2", "display_name": "vantage", "allowed_projects": '["vantage"]'}
        reconcile = AsyncMock(return_value=["c1"])
        with (
            patch("app.services.project_permission_service.reconcile_access_if_registry_changed", reconcile),
            patch.object(helpers, "get_cached_client", AsyncMock(return_value=fresh)),
        ):
            assert await helpers._with_current_registry_access("c1", stale) == fresh
            assert await helpers._with_current_registry_access("c2", other) == other
        reconcile.assert_awaited_once()
