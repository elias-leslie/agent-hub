"""Tests for usage tracking service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.usage_tracker import (
    METRIC_LOADED,
    METRIC_REFERENCED,
    METRIC_SUCCESS,
    UsageBuffer,
    get_usage_buffer,
    track_loaded,
    track_referenced,
    track_success,
)


class TestUsageBuffer:
    """Tests for UsageBuffer class."""

    def test_increment_loaded(self):
        """Test incrementing loaded counter."""
        buffer = UsageBuffer()
        uuid = "test-uuid-123"

        buffer.increment_loaded(uuid)
        buffer.increment_loaded(uuid)

        assert buffer._counters[uuid][METRIC_LOADED] == 2

    def test_increment_referenced(self):
        """Test incrementing referenced counter."""
        buffer = UsageBuffer()
        uuid = "test-uuid-123"

        buffer.increment_referenced(uuid)
        buffer.increment_referenced(uuid)
        buffer.increment_referenced(uuid)

        assert buffer._counters[uuid][METRIC_REFERENCED] == 3

    def test_increment_success(self):
        """Test incrementing success counter."""
        buffer = UsageBuffer()
        uuid = "test-uuid-123"

        buffer.increment_success(uuid)

        assert buffer._counters[uuid][METRIC_SUCCESS] == 1

    def test_multiple_uuids(self):
        """Test tracking multiple UUIDs separately."""
        buffer = UsageBuffer()

        buffer.increment_loaded("uuid-1")
        buffer.increment_loaded("uuid-1")
        buffer.increment_loaded("uuid-2")
        buffer.increment_referenced("uuid-2")

        assert buffer._counters["uuid-1"][METRIC_LOADED] == 2
        assert buffer._counters["uuid-1"][METRIC_REFERENCED] == 0
        assert buffer._counters["uuid-2"][METRIC_LOADED] == 1
        assert buffer._counters["uuid-2"][METRIC_REFERENCED] == 1

    def test_thread_safety_basic(self):
        """Test basic thread safety with lock acquisition."""
        buffer = UsageBuffer()
        uuid = "test-uuid"

        # Just verify lock is used
        assert buffer._lock is not None

        # Should not raise
        buffer.increment_loaded(uuid)
        buffer.increment_referenced(uuid)
        buffer.increment_success(uuid)


class TestUsageBufferFlush:
    """Tests for flush functionality."""

    @pytest.mark.asyncio
    async def test_flush_clears_counters(self):
        """Test that flush clears the internal counters."""
        buffer = UsageBuffer()

        buffer.increment_loaded("uuid-1")
        buffer.increment_referenced("uuid-1")

        # Mock the external calls
        with (
            patch.object(buffer, "_flush_to_neo4j", new_callable=AsyncMock) as mock_neo4j,
            patch.object(buffer, "_flush_to_postgres", new_callable=AsyncMock) as mock_pg,
        ):
            await buffer.flush()

            # Counters should be cleared
            assert len(buffer._counters) == 0

            # Both flush methods should be called
            mock_neo4j.assert_called_once()
            mock_pg.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_with_empty_buffer(self):
        """Test flush does nothing with empty buffer."""
        buffer = UsageBuffer()

        with (
            patch.object(buffer, "_flush_to_neo4j", new_callable=AsyncMock) as mock_neo4j,
            patch.object(buffer, "_flush_to_postgres", new_callable=AsyncMock) as mock_pg,
        ):
            await buffer.flush()

            # Neither should be called with empty buffer
            mock_neo4j.assert_not_called()
            mock_pg.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_restores_counters_on_neo4j_failure(self):
        """Test counters are restored if Neo4j flush fails."""
        buffer = UsageBuffer()

        buffer.increment_loaded("uuid-1")
        buffer.increment_loaded("uuid-1")

        with (
            patch.object(
                buffer,
                "_flush_to_neo4j",
                new_callable=AsyncMock,
                side_effect=Exception("Neo4j error"),
            ),
            patch.object(buffer, "_flush_to_postgres", new_callable=AsyncMock) as mock_pg,
        ):
            await buffer.flush()

            # Counters should be restored
            assert buffer._counters["uuid-1"][METRIC_LOADED] == 2

            # Postgres should NOT be called if Neo4j failed
            mock_pg.assert_not_called()


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_track_loaded(self):
        """Test track_loaded convenience function."""
        with patch("app.services.memory.usage_tracker.get_usage_buffer") as mock_get:
            mock_buffer = MagicMock()
            mock_get.return_value = mock_buffer

            track_loaded("test-uuid")

            mock_buffer.increment_loaded.assert_called_once_with("test-uuid")

    def test_track_referenced(self):
        """Test track_referenced convenience function."""
        with patch("app.services.memory.usage_tracker.get_usage_buffer") as mock_get:
            mock_buffer = MagicMock()
            mock_get.return_value = mock_buffer

            track_referenced("test-uuid")

            mock_buffer.increment_referenced.assert_called_once_with("test-uuid")

    def test_track_success(self):
        """Test track_success convenience function."""
        with patch("app.services.memory.usage_tracker.get_usage_buffer") as mock_get:
            mock_buffer = MagicMock()
            mock_get.return_value = mock_buffer

            track_success("test-uuid")

            mock_buffer.increment_success.assert_called_once_with("test-uuid")


class TestBufferSingleton:
    """Tests for singleton behavior."""

    def test_get_usage_buffer_returns_same_instance(self):
        """Test singleton pattern returns same instance."""
        # Reset global for test isolation
        import app.services.memory.usage_tracker as tracker_module

        tracker_module._usage_buffer = None

        buffer1 = get_usage_buffer()
        buffer2 = get_usage_buffer()

        assert buffer1 is buffer2


class TestMetricTypes:
    """Tests for metric type constants."""

    def test_metric_loaded_constant(self):
        """Test METRIC_LOADED constant value."""
        assert METRIC_LOADED == "loaded"

    def test_metric_referenced_constant(self):
        """Test METRIC_REFERENCED constant value."""
        assert METRIC_REFERENCED == "referenced"

    def test_metric_success_constant(self):
        """Test METRIC_SUCCESS constant value."""
        assert METRIC_SUCCESS == "success"
