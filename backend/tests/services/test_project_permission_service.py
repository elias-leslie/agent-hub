"""Tests for project permission service — tier logic, tool filtering, execution checks."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.project_permission import ProjectPermission
from app.services.project_permission_service import (
    TIER_TOOLS,
    ExecutionPermissionResult,
    check_execution_permission,
    check_tool_allowed,
    get_project_permission,
    get_tools_for_tier,
    list_project_permissions,
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
        assert "consult_agent" in tools
        assert "read_journal" in tools
        # Should NOT have write tools
        assert "write_file" not in tools
        assert "bash" not in tools

    def test_write_tier_includes_read_tools(self):
        read_tools = get_tools_for_tier("read")
        write_tools = get_tools_for_tier("write")
        assert read_tools.issubset(write_tools)
        assert "write_file" in write_tools
        assert "write_journal" in write_tools
        # Should NOT have yolo tools
        assert "bash" not in write_tools

    def test_yolo_tier_includes_all_tools(self):
        write_tools = get_tools_for_tier("write")
        yolo_tools = get_tools_for_tier("yolo")
        assert write_tools.issubset(yolo_tools)
        assert "bash" in yolo_tools
        assert "send_push" in yolo_tools
        assert "schedule_job" in yolo_tools

    def test_unknown_tier_returns_empty(self):
        assert get_tools_for_tier("nonexistent") == frozenset()

    def test_tiers_are_cumulative(self):
        """Each higher tier includes all tools from lower tiers."""
        off = TIER_TOOLS["off"]
        read = TIER_TOOLS["read"]
        write = TIER_TOOLS["write"]
        yolo = TIER_TOOLS["yolo"]
        assert off.issubset(read)
        assert read.issubset(write)
        assert write.issubset(yolo)

    def test_each_tier_adds_new_tools(self):
        """Each higher tier adds at least one tool not in the previous."""
        assert len(TIER_TOOLS["read"]) > len(TIER_TOOLS["off"])
        assert len(TIER_TOOLS["write"]) > len(TIER_TOOLS["read"])
        assert len(TIER_TOOLS["yolo"]) > len(TIER_TOOLS["write"])


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
    perm.updated_at = datetime.now(timezone.utc)
    perm.created_at = datetime.now(timezone.utc)
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
                mock_db, "proj", permission_tier="yolo"
            )
            assert result.permission_tier == "yolo"
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
    async def test_yolo_tier_allows_bash(self):
        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="yolo",
        ):
            allowed, _ = await check_tool_allowed("proj", "bash")
            assert allowed is True

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
# Execution permission checks
# ---------------------------------------------------------------------------


class TestCheckExecutionPermission:
    @pytest.mark.asyncio
    async def test_allowed_when_all_conditions_met(self):
        mock_perm = _make_permission("proj", "yolo", auto_exec=True, start_hour=0, end_hour=24)
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
        mock_perm = _make_permission("proj", "yolo", auto_exec=False)
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
            "proj", "yolo", auto_exec=True,
            start_hour=bad_hour, end_hour=(bad_hour + 1) % 24 or 24,
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm
        mock_db.execute.return_value = mock_result

        result = await check_execution_permission(mock_db, "proj")
        assert result.allowed is False
        assert result.reason == "outside_execution_hours"
