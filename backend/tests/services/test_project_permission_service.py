"""Tests for project permission service — tier logic, tool filtering, execution checks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.project_permission import ProjectPermission
from app.services.project_permission_service import (
    _PERSONA_INTERNAL,
    _PERSONA_OPERATIONAL,
    _PERSONA_TOOLS,
    TIER_TOOLS,
    check_execution_permission,
    check_tool_allowed,
    create_project_permission,
    delete_project_permission,
    get_project_permission,
    get_tools_for_tier,
    get_visible_tools_for_tier,
    list_project_permissions,
    reconcile_registered_project_access,
    update_project_permission,
)

# ---------------------------------------------------------------------------
# Tier logic
# ---------------------------------------------------------------------------


class TestTierTools:
    """Tests for get_tools_for_tier and TIER_TOOLS mapping."""

    def test_off_tier_has_no_tools(self):
        assert get_tools_for_tier("off") == frozenset()

    def test_read_tier_has_read_tools(self):
        tools = get_tools_for_tier("read")
        assert "read_file" in tools
        # Read-only network ops are read-class — same shape as read_file but
        # over the open web. Required by agents like vantage-research.
        assert "research_web" in tools
        assert "search_web" in tools
        assert "fetch_web_page" in tools
        assert "search_scratch_context" not in tools
        assert "precision_code_search" not in tools
        assert "write_file" not in tools
        assert "bash" not in tools

    def test_full_tier_includes_core_tools(self):
        read_tools = get_tools_for_tier("read")
        full_tools = get_tools_for_tier("full")
        assert read_tools.issubset(full_tools)
        assert "bash" in full_tools
        assert "batch_execute" not in full_tools
        assert "search_scratch_context" in full_tools
        assert "write_file" in full_tools
        assert "send_push" not in full_tools
        assert "schedule_job" not in full_tools

    def test_legacy_write_and_yolo_alias_full(self):
        full_tools = get_tools_for_tier("full")
        assert get_tools_for_tier("write") == full_tools
        assert get_tools_for_tier("yolo") == full_tools

    def test_unknown_tier_returns_empty(self):
        assert get_tools_for_tier("nonexistent") == frozenset()

    def test_tiers_are_cumulative(self):
        """Each higher tier includes all tools from lower tiers."""
        off = TIER_TOOLS["off"]
        read = TIER_TOOLS["read"]
        full = TIER_TOOLS["full"]
        assert off.issubset(read)
        assert read.issubset(full)

    def test_each_tier_adds_new_tools(self):
        """Each higher tier adds at least one tool not in the previous."""
        assert len(TIER_TOOLS["read"]) > len(TIER_TOOLS["off"])
        assert len(TIER_TOOLS["full"]) > len(TIER_TOOLS["read"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_permission(
    project_id: str = "test-project",
    tier: str = "read",
    auto_exec: bool = False,
    start_hour: int = 0,
    end_hour: int = 24,
    root_path: str | None = None,
) -> ProjectPermission:
    """Create a mock ProjectPermission object."""
    perm = MagicMock(spec=ProjectPermission)
    perm.project_id = project_id
    perm.permission_tier = tier
    perm.auto_exec_enabled = auto_exec
    perm.execution_start_hour = start_hour
    perm.execution_end_hour = end_hour
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
        mock_perm = _make_permission("summitflow", "write")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        result = await get_project_permission(mock_db, "summitflow")
        assert result is not None
        assert result.project_id == "summitflow"
        assert result.permission_tier == "write"

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
    async def test_updates_tier(self):
        mock_perm = _make_permission("proj", "read")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        with patch(
            "app.services.project_permission_service._invalidate_cache",
            new_callable=AsyncMock,
        ):
            result = await update_project_permission(
                mock_db, "proj", permission_tier="full"
            )
            assert result is not None
            assert result.permission_tier == "full"
            mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_project(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await update_project_permission(
            mock_db, "nonexistent", permission_tier="write"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_rejects_invalid_tier(self):
        mock_perm = _make_permission("proj", "read")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Invalid tier"):
            await update_project_permission(
                mock_db, "proj", permission_tier="invalid"
            )

    @pytest.mark.asyncio
    async def test_updates_registered_project_access_for_summitflow_clients(self):
        mock_perm = _make_permission("test2", "read")
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
                "app.services.project_permission_service._invalidate_cache",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.project_permission_service.invalidate_client_cache"
            ) as mock_invalidate_client_cache,
        ):
            result = await update_project_permission(
                mock_db, "test2", permission_tier="full"
            )

        assert result is not None
        assert result.permission_tier == "full"
        assert summitflow_client.allowed_projects == '["summitflow", "test2"]'
        assert backend_client.allowed_projects == '["summitflow", "agent-hub", "test2"]'
        assert other_client.allowed_projects == '["portfolio-ai"]'
        mock_invalidate_client_cache.assert_any_call("client-summitflow")
        mock_invalidate_client_cache.assert_any_call("client-backend")
        assert mock_invalidate_client_cache.call_count == 2

    @pytest.mark.asyncio
    async def test_removes_disabled_project_from_summitflow_clients(self):
        mock_perm = _make_permission("test2", "full")
        summitflow_client = MagicMock()
        summitflow_client.id = "client-summitflow"
        summitflow_client.display_name = "SummitFlow"
        summitflow_client.allowed_projects = '["summitflow", "test2"]'
        backend_client = MagicMock()
        backend_client.id = "client-backend"
        backend_client.display_name = "summitflow-backend"
        backend_client.allowed_projects = '["summitflow","agent-hub","test2"]'

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
                "app.services.project_permission_service._invalidate_cache",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.project_permission_service.invalidate_client_cache"
            ) as mock_invalidate_client_cache,
        ):
            result = await update_project_permission(
                mock_db, "test2", permission_tier="off"
            )

        assert result is not None
        assert result.permission_tier == "off"
        assert summitflow_client.allowed_projects == '["summitflow"]'
        assert backend_client.allowed_projects == '["summitflow", "agent-hub"]'
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
                "app.services.project_permission_service.resolve_project_root",
                return_value=Path("/srv/workspaces/projects/test2"),
            ),
            patch(
                "app.services.project_permission_service._invalidate_cache",
                new_callable=AsyncMock,
            ),
            patch("app.services.project_permission_service.invalidate_project_cache"),
        ):
            result = await create_project_permission(
                mock_db,
                "test2",
                permission_tier="full",
                auto_exec_enabled=True,
            )

        assert result is created["perm"]
        assert created["perm"].project_id == "test2"
        assert created["perm"].permission_tier == "full"
        assert created["perm"].auto_exec_enabled is True
        assert created["perm"].root_path == "/srv/workspaces/projects/test2"
        mock_db.commit.assert_awaited_once()
        mock_db.refresh.assert_awaited_once_with(created["perm"])

    @pytest.mark.asyncio
    async def test_rejects_duplicate_project(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = _make_permission("proj", "read")
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="already exists"):
            await create_project_permission(mock_db, "proj")


class TestReconcileRegisteredProjectAccess:
    @pytest.mark.asyncio
    async def test_repairs_missing_registered_project_access(self):
        permissions = [
            _make_permission("agent-hub", "read"),
            _make_permission("summitflow", "full"),
            _make_permission("test1", "full"),
            _make_permission("vantage", "read"),
            _make_permission("old-project", "off"),
        ]
        summitflow_client = MagicMock()
        summitflow_client.id = "client-summitflow"
        summitflow_client.display_name = "SummitFlow"
        summitflow_client.allowed_projects = (
            '["summitflow","st-cli","agent-hub","test1","old-project"]'
        )
        backend_client = MagicMock()
        backend_client.id = "client-backend"
        backend_client.display_name = "summitflow-backend"
        backend_client.allowed_projects = '["summitflow","agent-hub","old-project"]'
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
    async def test_noops_when_registered_access_is_aligned(self):
        permissions = [
            _make_permission("agent-hub", "read"),
            _make_permission("summitflow", "full"),
            _make_permission("test1", "full"),
            _make_permission("vantage", "read"),
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
    async def test_rejects_invalid_tier(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Invalid tier"):
            await create_project_permission(mock_db, "proj", permission_tier="bad")

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
                "app.services.project_permission_service.resolve_project_root",
                return_value=Path("/srv/workspaces/projects/test2"),
            ),
            patch(
                "app.services.project_permission_service._invalidate_cache",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.project_permission_service.invalidate_client_cache"
            ) as mock_invalidate_client_cache,
            patch("app.services.project_permission_service.invalidate_project_cache"),
        ):
            result = await create_project_permission(
                mock_db,
                "test2",
                permission_tier="full",
                auto_exec_enabled=True,
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
        mock_perm = _make_permission("test2", "full")
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
                "app.services.project_permission_service._invalidate_cache",
                new_callable=AsyncMock,
            ),
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


# ---------------------------------------------------------------------------
# Tool permission checks
# ---------------------------------------------------------------------------


class TestCheckToolAllowed:
    @pytest.mark.asyncio
    async def test_allowed_tool_at_read_tier(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed("proj", "read_file")
            assert allowed is True
            assert reason == "allowed"

    @pytest.mark.asyncio
    async def test_tool_search_denied_at_read_tier(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed("proj", "tool_search")
            assert allowed is False
            assert "not permitted" in reason

    @pytest.mark.asyncio
    async def test_search_scratch_context_denied_at_read_tier(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed("proj", "search_scratch_context")
            assert allowed is False
            assert "not permitted" in reason

    @pytest.mark.asyncio
    async def test_search_web_allowed_at_read_tier(self):
        # Read-only network ops are read-class (same shape as read_file but
        # over the open web). Allowed at read+ tier so agents like
        # vantage-research can call them without requiring full tier.
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, _ = await check_tool_allowed("proj", "search_web")
            assert allowed is True

    @pytest.mark.asyncio
    async def test_research_web_allowed_at_read_tier(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, _ = await check_tool_allowed("proj", "research_web")
            assert allowed is True

    @pytest.mark.asyncio
    async def test_fetch_web_page_allowed_at_read_tier(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, _ = await check_tool_allowed("proj", "fetch_web_page")
            assert allowed is True

    @pytest.mark.asyncio
    async def test_denied_tool_at_read_tier(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed("proj", "bash")
            assert allowed is False
            assert "not permitted" in reason

    @pytest.mark.asyncio
    async def test_full_tier_allows_bash(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="full",
        ):
            allowed, _ = await check_tool_allowed("proj", "bash")
            assert allowed is True

    @pytest.mark.asyncio
    async def test_full_tier_allows_scratch_lookup(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="full",
        ):
            allowed, _ = await check_tool_allowed("proj", "search_scratch_context")
            assert allowed is True

    @pytest.mark.asyncio
    async def test_full_tier_denies_batch_execute(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="full",
        ):
            allowed, _ = await check_tool_allowed("proj", "batch_execute")
            assert allowed is False

    @pytest.mark.asyncio
    async def test_off_tier_denies_everything(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="off",
        ):
            allowed, _ = await check_tool_allowed("proj", "read_file")
            assert allowed is False

    @pytest.mark.asyncio
    async def test_falls_back_to_db_on_cache_miss(self):
        mock_perm = _make_permission("proj", "write")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        with (
            patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.project_permission_service._set_cache",
                new_callable=AsyncMock,
            ) as mock_set_cache,
        ):
            allowed, _ = await check_tool_allowed("proj", "write_file", db=mock_db)
            assert allowed is True
            mock_set_cache.assert_awaited_once()


# ---------------------------------------------------------------------------
# Persona tool tier exemptions
# ---------------------------------------------------------------------------


class TestPersonaToolSets:
    """Verify persona tool set composition and membership."""

    def test_internal_and_operational_are_disjoint(self):
        assert frozenset() == _PERSONA_INTERNAL & _PERSONA_OPERATIONAL

    def test_persona_tools_is_union(self):
        assert _PERSONA_TOOLS == _PERSONA_INTERNAL | _PERSONA_OPERATIONAL

    def test_internal_contains_identity_tools(self):
        for tool in (
            "read_personality",
            "write_personality",
            "read_user_context",
            "write_user_context",
            "review_memory_system",
        ):
            assert tool in _PERSONA_INTERNAL

    def test_visible_read_tier_stays_core_only(self):
        tools = get_visible_tools_for_tier("read")

        assert tools == frozenset({
            "read_file",
            "research_web",
            "search_web",
            "fetch_web_page",
            # Vantage mode-recommendation tools: I/O-free, structured-JSON
            # output for downstream UI; safe at read tier.
            "propose_thorough",
            "propose_committee",
            "propose_honing",
            # Vantage intake/scoping signal tool — pure pass-through, no I/O.
            "start_research",
        })

    def test_operational_contains_agency_tools(self):
        for tool in (
            "manage_tasks",
            "schedule_job",
            "list_scheduled_jobs",
            "cancel_scheduled_job",
            "send_push",
            "steer_consultation",
            "list_consultations",
            "cancel_consultation",
            "inspect_session",
        ):
            assert tool in _PERSONA_OPERATIONAL


class TestPersonaToolTierExemption:
    """Persona tools bypass project tier (except 'off')."""

    @pytest.mark.asyncio
    async def test_internal_tool_allowed_at_read_tier(self):
        """write_personality is not in _READ_TOOLS but is tier-exempt."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed("proj", "write_personality")
            assert allowed is True
            assert "persona-internal" in reason

    @pytest.mark.asyncio
    async def test_memory_review_tool_allowed_at_read_tier(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed("proj", "review_memory_system")
            assert allowed is True
            assert "persona-internal" in reason

    @pytest.mark.asyncio
    async def test_safe_operational_tool_allowed_at_read_tier(self):
        """Safe persona-ops like scheduling remain tier-exempt at read tier."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed("proj", "schedule_job")
            assert allowed is True
            assert "persona-internal" in reason

    @pytest.mark.asyncio
    async def test_operational_tool_allowed_at_legacy_write_tier(self):
        """schedule_job should tolerate legacy write alias."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="write",
        ):
            allowed, reason = await check_tool_allowed("proj", "schedule_job")
            assert allowed is True
            assert "persona-internal" in reason

    @pytest.mark.asyncio
    async def test_manage_tasks_overview_denied_at_read_tier(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed(
                "proj", "manage_tasks", tool_input={"action": "overview"},
            )
            assert allowed is False
            assert "direct helper tool disabled" in reason

    @pytest.mark.asyncio
    async def test_manage_tasks_dispatch_denied_at_read_tier(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed(
                "proj", "manage_tasks", tool_input={"action": "dispatch"},
            )
            assert allowed is False
            assert "direct helper tool disabled" in reason

    @pytest.mark.asyncio
    async def test_dispatch_agent_denied_at_read_tier(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed("proj", "dispatch_agent")
            assert allowed is False
            assert "direct helper tool disabled" in reason

    @pytest.mark.asyncio
    async def test_persona_tool_denied_at_off_tier(self):
        """Even persona tools are blocked when tier is 'off'."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="off",
        ):
            allowed, reason = await check_tool_allowed("proj", "write_personality")
            assert allowed is False
            assert "off" in reason

    @pytest.mark.asyncio
    async def test_operational_tool_denied_at_off_tier(self):
        """Operational persona tools are also blocked at 'off'."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="off",
        ):
            allowed, reason = await check_tool_allowed("proj", "send_push")
            assert allowed is False
            assert "off" in reason

    @pytest.mark.asyncio
    async def test_non_persona_tool_still_gated_by_tier(self):
        """bash is NOT a persona tool and should still be gated normally."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="read",
        ):
            allowed, reason = await check_tool_allowed("proj", "bash")
            assert allowed is False
            assert "not permitted" in reason


# ---------------------------------------------------------------------------
# Execution permission checks
# ---------------------------------------------------------------------------


class TestCheckExecutionPermission:
    @pytest.mark.asyncio
    async def test_allowed_when_all_conditions_met(self):
        mock_perm = _make_permission(
            "proj", "full", auto_exec=True, start_hour=0, end_hour=24
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        result = await check_execution_permission(mock_db, "proj")
        assert result.allowed is True
        assert result.reason == "allowed"

    @pytest.mark.asyncio
    async def test_denied_when_tier_off(self):
        mock_perm = _make_permission("proj", "off", auto_exec=True)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        result = await check_execution_permission(mock_db, "proj")
        assert result.allowed is False
        assert result.reason == "permission_tier_off"

    @pytest.mark.asyncio
    async def test_denied_when_auto_exec_disabled(self):
        mock_perm = _make_permission("proj", "full", auto_exec=False)
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        result = await check_execution_permission(mock_db, "proj")
        assert result.allowed is False
        assert result.reason == "auto_exec_disabled"

    @pytest.mark.asyncio
    async def test_denied_when_project_not_found(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await check_execution_permission(mock_db, "nonexistent")
        assert result.allowed is False
        assert result.reason == "project_not_found"

    @pytest.mark.asyncio
    async def test_denied_when_outside_time_window(self):
        # Set window to a time that definitely doesn't contain current hour
        current_hour = datetime.now().hour
        # Pick a 1-hour window that doesn't contain current hour
        bad_hour = (current_hour + 12) % 24
        mock_perm = _make_permission(
            "proj",
            "full",
            auto_exec=True,
            start_hour=bad_hour,
            end_hour=(bad_hour + 1) % 24 or 24,
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        result = await check_execution_permission(mock_db, "proj")
        assert result.allowed is False
        assert result.reason == "outside_execution_hours"


# ---------------------------------------------------------------------------
# Time window edge cases (deterministic via mocked datetime)
# ---------------------------------------------------------------------------


def _mock_db_with_permission(perm):
    """Create a mock AsyncSession that returns the given permission."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = perm
    mock_db.execute.return_value = mock_result
    return mock_db


def _patch_current_hour(hour: int):
    """Patch datetime.now() in the service module to return a fixed hour."""
    mock_dt = MagicMock(wraps=datetime)
    mock_now = MagicMock()
    mock_now.hour = hour
    mock_dt.now.return_value = mock_now
    return patch("app.services.project_permission_service.datetime", mock_dt)


class TestTimeWindowEdgeCases:
    """Deterministic tests for time window logic edge cases."""

    # -- Full day: start=0, end=24 -- should always allow -----------------

    @pytest.mark.asyncio
    async def test_full_day_window_allows_at_midnight(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=0, end_hour=24)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(0):
            result = await check_execution_permission(db, "p")
        assert result.allowed is True
        assert result.in_time_window is True

    @pytest.mark.asyncio
    async def test_full_day_window_allows_at_noon(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=0, end_hour=24)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(12):
            result = await check_execution_permission(db, "p")
        assert result.allowed is True
        assert result.in_time_window is True

    @pytest.mark.asyncio
    async def test_full_day_window_allows_at_hour_23(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=0, end_hour=24)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(23):
            result = await check_execution_permission(db, "p")
        assert result.allowed is True
        assert result.in_time_window is True

    # -- Wrap-around overnight: start=22, end=6 ---------------------------

    @pytest.mark.asyncio
    async def test_overnight_window_allows_at_23(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=22, end_hour=6)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(23):
            result = await check_execution_permission(db, "p")
        assert result.allowed is True
        assert result.in_time_window is True

    @pytest.mark.asyncio
    async def test_overnight_window_allows_at_midnight(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=22, end_hour=6)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(0):
            result = await check_execution_permission(db, "p")
        assert result.allowed is True
        assert result.in_time_window is True

    @pytest.mark.asyncio
    async def test_overnight_window_allows_at_3am(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=22, end_hour=6)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(3):
            result = await check_execution_permission(db, "p")
        assert result.allowed is True
        assert result.in_time_window is True

    @pytest.mark.asyncio
    async def test_overnight_window_allows_at_start_boundary(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=22, end_hour=6)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(22):
            result = await check_execution_permission(db, "p")
        assert result.allowed is True
        assert result.in_time_window is True

    @pytest.mark.asyncio
    async def test_overnight_window_denies_at_end_boundary(self):
        """End hour is exclusive, so hour=6 should be outside the 22-6 window."""
        perm = _make_permission("p", "full", auto_exec=True, start_hour=22, end_hour=6)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(6):
            result = await check_execution_permission(db, "p")
        assert result.allowed is False
        assert result.in_time_window is False
        assert result.reason == "outside_execution_hours"

    @pytest.mark.asyncio
    async def test_overnight_window_denies_at_noon(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=22, end_hour=6)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(12):
            result = await check_execution_permission(db, "p")
        assert result.allowed is False
        assert result.in_time_window is False

    @pytest.mark.asyncio
    async def test_overnight_window_denies_at_21(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=22, end_hour=6)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(21):
            result = await check_execution_permission(db, "p")
        assert result.allowed is False
        assert result.in_time_window is False

    # -- Midnight boundary: start=0, end=0 -- zero-length, never allowed --

    @pytest.mark.asyncio
    async def test_midnight_zero_zero_denies_at_midnight(self):
        """start=0, end=0 is a zero-length window and should never allow."""
        perm = _make_permission("p", "full", auto_exec=True, start_hour=0, end_hour=0)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(0):
            result = await check_execution_permission(db, "p")
        assert result.allowed is False
        assert result.in_time_window is False
        assert result.reason == "outside_execution_hours"

    @pytest.mark.asyncio
    async def test_midnight_zero_zero_denies_at_noon(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=0, end_hour=0)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(12):
            result = await check_execution_permission(db, "p")
        assert result.allowed is False
        assert result.in_time_window is False

    # -- Same hour: start=10, end=10 -- zero-length, never allowed --------

    @pytest.mark.asyncio
    async def test_same_hour_denies_at_that_hour(self):
        """start=10, end=10 is zero-length and should deny even at hour 10."""
        perm = _make_permission("p", "full", auto_exec=True, start_hour=10, end_hour=10)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(10):
            result = await check_execution_permission(db, "p")
        assert result.allowed is False
        assert result.in_time_window is False
        assert result.reason == "outside_execution_hours"

    @pytest.mark.asyncio
    async def test_same_hour_denies_at_other_hour(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=10, end_hour=10)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(15):
            result = await check_execution_permission(db, "p")
        assert result.allowed is False
        assert result.in_time_window is False

    # -- Normal daytime window: start=9, end=17 ----------------------------

    @pytest.mark.asyncio
    async def test_normal_window_allows_inside(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=9, end_hour=17)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(12):
            result = await check_execution_permission(db, "p")
        assert result.allowed is True
        assert result.in_time_window is True

    @pytest.mark.asyncio
    async def test_normal_window_allows_at_start_boundary(self):
        """Start hour is inclusive."""
        perm = _make_permission("p", "full", auto_exec=True, start_hour=9, end_hour=17)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(9):
            result = await check_execution_permission(db, "p")
        assert result.allowed is True
        assert result.in_time_window is True

    @pytest.mark.asyncio
    async def test_normal_window_denies_at_end_boundary(self):
        """End hour is exclusive."""
        perm = _make_permission("p", "full", auto_exec=True, start_hour=9, end_hour=17)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(17):
            result = await check_execution_permission(db, "p")
        assert result.allowed is False
        assert result.in_time_window is False

    @pytest.mark.asyncio
    async def test_normal_window_denies_before_start(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=9, end_hour=17)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(8):
            result = await check_execution_permission(db, "p")
        assert result.allowed is False
        assert result.in_time_window is False

    # -- Single-hour window: start=10, end=11 ------------------------------

    @pytest.mark.asyncio
    async def test_single_hour_window_allows_at_that_hour(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=10, end_hour=11)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(10):
            result = await check_execution_permission(db, "p")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_single_hour_window_denies_adjacent(self):
        perm = _make_permission("p", "full", auto_exec=True, start_hour=10, end_hour=11)
        db = _mock_db_with_permission(perm)
        with _patch_current_hour(11):
            result = await check_execution_permission(db, "p")
        assert result.allowed is False


# ---------------------------------------------------------------------------
# Fail-closed error handling tests
# ---------------------------------------------------------------------------


class TestCheckToolAllowedFailClosed:
    """Verify that check_tool_allowed denies access on all error paths."""

    @pytest.mark.asyncio
    async def test_redis_error_with_db_fallback(self):
        """When Redis raises, should fall back to DB and still work."""
        mock_perm = _make_permission("proj", "write")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        with (
            patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                side_effect=Exception("Redis connection refused"),
            ),
            patch(
                "app.services.project_permission_service._set_cache",
                new_callable=AsyncMock,
            ),
        ):
            # _get_cached_tier already catches exceptions and returns None,
            # but if it somehow propagated, the outer try/except catches it.
            # Here we test: the outer try/except catches the error and denies.
            allowed, reason = await check_tool_allowed(
                "proj", "write_file", db=mock_db
            )
            assert allowed is False
            assert "permission check error" in reason

    @pytest.mark.asyncio
    async def test_db_unavailable_denies(self):
        """When both cache misses and DB raises, should deny (not crash)."""
        with (
            patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            mock_db = AsyncMock()
            mock_db.execute.side_effect = Exception("DB connection refused")

            allowed, reason = await check_tool_allowed(
                "proj", "read_file", db=mock_db
            )
            assert allowed is False
            assert "permission check error" in reason

    @pytest.mark.asyncio
    async def test_unknown_project_denies(self):
        """When project has no permission record, should deny (fail-closed)."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value=None,
        ):
            allowed, reason = await check_tool_allowed(
                "unknown-proj", "read_file", db=mock_db
            )
            assert allowed is False
            assert "no permission record" in reason

    @pytest.mark.asyncio
    async def test_unrecognized_tier_from_cache_denies(self):
        """When Redis returns an unrecognized tier value, should deny."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="super_admin",  # Not in TIER_TOOLS
        ):
            allowed, reason = await check_tool_allowed("proj", "read_file")
            assert allowed is False
            assert "unrecognized permission tier" in reason

    @pytest.mark.asyncio
    async def test_unrecognized_tier_from_db_denies(self):
        """When DB returns an unrecognized tier value, should deny."""
        mock_perm = _make_permission("proj", "bogus_tier")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        with (
            patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.project_permission_service._set_cache",
                new_callable=AsyncMock,
            ),
        ):
            allowed, reason = await check_tool_allowed("proj", "read_file", db=mock_db)
            assert allowed is False
            assert "unrecognized permission tier" in reason

    @pytest.mark.asyncio
    async def test_never_raises_on_any_error(self):
        """check_tool_allowed should never raise; always returns a tuple."""
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            side_effect=RuntimeError("catastrophic failure"),
        ):
            # Should not raise
            allowed, reason = await check_tool_allowed("proj", "bash")
            assert allowed is False
            assert "permission check error" in reason
