"""Tests for memory settings service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.memory.settings import (
    DEFAULT_ENABLED,
    DEFAULT_TOTAL_BUDGET,
    MemorySettingsDTO,
    get_memory_settings,
    update_memory_settings,
)


class TestMemorySettingsDTO:
    """Tests for MemorySettingsDTO dataclass."""

    def test_creation(self):
        """Test DTO creation with values."""
        dto = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
        assert dto.enabled is True
        assert dto.budget_enabled is True
        assert dto.total_budget == 3500

    def test_disabled_settings(self):
        """Test DTO with disabled memory."""
        dto = MemorySettingsDTO(enabled=False, budget_enabled=False, total_budget=1000)
        assert dto.enabled is False
        assert dto.budget_enabled is False
        assert dto.total_budget == 1000


class TestGetMemorySettings:
    """Tests for get_memory_settings function."""

    @pytest.mark.asyncio
    async def test_get_settings_returns_defaults_when_no_settings(self):
        """Test that defaults are returned when no settings in DB."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await get_memory_settings(db=mock_session)

        assert result.enabled == DEFAULT_ENABLED
        assert result.total_budget == DEFAULT_TOTAL_BUDGET

    @pytest.mark.asyncio
    async def test_returns_stored_settings(self):
        """Test that stored settings are returned."""
        mock_settings = MagicMock()
        mock_settings.enabled = False
        mock_settings.total_budget = 5000

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_settings
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await get_memory_settings(db=mock_session)

        assert result.enabled is False
        assert result.total_budget == 5000


class TestUpdateMemorySettings:
    """Tests for update_memory_settings function."""

    @pytest.mark.asyncio
    async def test_creates_settings_when_none_exist(self):
        """Test that settings are created if they don't exist."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Mock the add and refresh methods
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        # Create a mock that captures the settings object
        captured_settings = None

        def capture_add(obj):
            nonlocal captured_settings
            captured_settings = obj

        mock_session.add = capture_add

        async def mock_refresh(obj):
            # Simulate refresh - settings should already have the values
            pass

        mock_session.refresh = mock_refresh

        await update_memory_settings(
            db=mock_session,
            enabled=True,
            total_budget=3000,
        )

        # Verify the settings object was created with correct values
        assert captured_settings is not None
        assert captured_settings.enabled is True
        assert captured_settings.total_budget == 3000

    @pytest.mark.asyncio
    async def test_update_settings_updates_existing_settings(self):
        """Test that existing settings are updated."""
        mock_settings = MagicMock()
        mock_settings.id = 1
        mock_settings.enabled = True
        mock_settings.total_budget = 2000

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_settings
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        await update_memory_settings(
            db=mock_session,
            enabled=False,
            total_budget=4000,
        )

        # Verify settings were updated
        assert mock_settings.enabled is False
        assert mock_settings.total_budget == 4000

    @pytest.mark.asyncio
    async def test_partial_update_enabled_only(self):
        """Test updating only enabled flag."""
        mock_settings = MagicMock()
        mock_settings.id = 1
        mock_settings.enabled = True
        mock_settings.total_budget = 2000

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_settings
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        await update_memory_settings(
            db=mock_session,
            enabled=False,
            # total_budget not provided
        )

        # Only enabled should be updated
        assert mock_settings.enabled is False
        assert mock_settings.total_budget == 2000  # Unchanged

    @pytest.mark.asyncio
    async def test_partial_update_budget_only(self):
        """Test updating only budget."""
        mock_settings = MagicMock()
        mock_settings.id = 1
        mock_settings.enabled = True
        mock_settings.total_budget = 2000

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_settings
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        await update_memory_settings(
            db=mock_session,
            total_budget=5000,
            # enabled not provided
        )

        # Only budget should be updated
        assert mock_settings.enabled is True  # Unchanged
        assert mock_settings.total_budget == 5000


class TestDefaultValues:
    """Tests for default value constants."""

    def test_default_enabled_is_true(self):
        """Test that default enabled is True."""
        assert DEFAULT_ENABLED is True

    def test_default_budget_is_3500(self):
        """Test that default budget is 3500 tokens."""
        assert DEFAULT_TOTAL_BUDGET == 3500
