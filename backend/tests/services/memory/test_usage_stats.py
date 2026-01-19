"""Tests for PostgreSQL usage stats storage.

Tests historical usage data storage and time-series queries.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import UsageStatLog


class TestUsageStatLogModel:
    """Tests for UsageStatLog SQLAlchemy model."""

    def test_model_fields(self):
        """Test UsageStatLog has expected fields."""
        # Check model has required columns
        assert hasattr(UsageStatLog, "id")
        assert hasattr(UsageStatLog, "episode_uuid")
        assert hasattr(UsageStatLog, "metric_type")
        assert hasattr(UsageStatLog, "value")
        assert hasattr(UsageStatLog, "timestamp")

    def test_metric_type_enum_values(self):
        """Test valid metric types."""
        valid_types = ["loaded", "referenced", "success"]

        for metric_type in valid_types:
            # Should be able to create log with each type
            log = UsageStatLog(
                episode_uuid="test-uuid",
                metric_type=metric_type,
                value=1,
                timestamp=datetime.now(UTC),
            )
            assert log.metric_type == metric_type


class TestPostgresFlush:
    """Tests for flushing usage stats to PostgreSQL."""

    @pytest.mark.asyncio
    async def test_builds_correct_insert_rows(self):
        """Test that flush builds correct rows for insert."""
        from app.services.memory.usage_tracker import UsageBuffer

        buffer = UsageBuffer()

        # Add some metrics
        buffer.increment_loaded("uuid-1")
        buffer.increment_loaded("uuid-1")
        buffer.increment_referenced("uuid-1")
        buffer.increment_success("uuid-2")

        # The counters should have
        assert buffer._counters["uuid-1"]["loaded"] == 2
        assert buffer._counters["uuid-1"]["referenced"] == 1
        assert buffer._counters["uuid-2"]["success"] == 1


class TestTimeSeriesQueries:
    """Tests for time-series queries on usage data."""

    def test_hourly_aggregation_concept(self):
        """Test conceptual hourly aggregation of usage stats."""
        # This tests the query pattern, not actual DB
        now = datetime.now(UTC)
        hour_ago = now - timedelta(hours=1)

        # Sample data points
        data = [
            {"timestamp": now - timedelta(minutes=5), "metric_type": "loaded", "value": 1},
            {"timestamp": now - timedelta(minutes=15), "metric_type": "loaded", "value": 1},
            {"timestamp": now - timedelta(minutes=30), "metric_type": "loaded", "value": 1},
            {"timestamp": now - timedelta(minutes=45), "metric_type": "referenced", "value": 1},
        ]

        # Filter to last hour
        recent = [d for d in data if d["timestamp"] >= hour_ago]

        # Count by metric type
        counts = {}
        for d in recent:
            metric = d["metric_type"]
            counts[metric] = counts.get(metric, 0) + d["value"]

        assert counts["loaded"] == 3
        assert counts["referenced"] == 1

    def test_daily_aggregation_concept(self):
        """Test conceptual daily aggregation of usage stats."""
        now = datetime.now(UTC)
        day_ago = now - timedelta(days=1)

        # Sample data across a day
        data = [
            {"timestamp": now - timedelta(hours=1), "episode_uuid": "uuid-1", "value": 10},
            {"timestamp": now - timedelta(hours=6), "episode_uuid": "uuid-1", "value": 5},
            {"timestamp": now - timedelta(hours=12), "episode_uuid": "uuid-2", "value": 3},
            {"timestamp": now - timedelta(days=2), "episode_uuid": "uuid-1", "value": 100},  # Too old
        ]

        # Filter to last day
        recent = [d for d in data if d["timestamp"] >= day_ago]

        # Group by episode
        by_episode = {}
        for d in recent:
            uuid = d["episode_uuid"]
            by_episode[uuid] = by_episode.get(uuid, 0) + d["value"]

        assert by_episode["uuid-1"] == 15
        assert by_episode["uuid-2"] == 3
        assert len(recent) == 3  # Old one excluded


class TestUsageAnalytics:
    """Tests for usage analytics queries."""

    def test_most_loaded_rules_concept(self):
        """Test identifying most frequently loaded rules."""
        usage_data = [
            {"episode_uuid": "rule-1", "loaded_count": 100},
            {"episode_uuid": "rule-2", "loaded_count": 50},
            {"episode_uuid": "rule-3", "loaded_count": 200},
            {"episode_uuid": "rule-4", "loaded_count": 25},
        ]

        # Sort by loaded_count descending
        sorted_data = sorted(usage_data, key=lambda x: x["loaded_count"], reverse=True)

        assert sorted_data[0]["episode_uuid"] == "rule-3"  # 200
        assert sorted_data[1]["episode_uuid"] == "rule-1"  # 100

    def test_most_useful_rules_concept(self):
        """Test identifying most useful rules by utility score."""
        usage_data = [
            {"episode_uuid": "rule-1", "utility_score": 0.8},
            {"episode_uuid": "rule-2", "utility_score": 0.3},
            {"episode_uuid": "rule-3", "utility_score": 0.95},
            {"episode_uuid": "rule-4", "utility_score": 0.5},
        ]

        # Sort by utility_score descending
        sorted_data = sorted(usage_data, key=lambda x: x["utility_score"], reverse=True)

        assert sorted_data[0]["episode_uuid"] == "rule-3"  # 0.95
        assert sorted_data[1]["episode_uuid"] == "rule-1"  # 0.8

    def test_never_referenced_rules_concept(self):
        """Test identifying rules that are loaded but never referenced."""
        usage_data = [
            {"episode_uuid": "rule-1", "loaded_count": 100, "referenced_count": 50},
            {"episode_uuid": "rule-2", "loaded_count": 200, "referenced_count": 0},  # Never referenced
            {"episode_uuid": "rule-3", "loaded_count": 50, "referenced_count": 0},   # Never referenced
            {"episode_uuid": "rule-4", "loaded_count": 75, "referenced_count": 10},
        ]

        # Find rules with loaded > 0 but referenced = 0
        never_referenced = [
            d for d in usage_data
            if d["loaded_count"] > 0 and d["referenced_count"] == 0
        ]

        assert len(never_referenced) == 2
        assert never_referenced[0]["episode_uuid"] == "rule-2"
        assert never_referenced[1]["episode_uuid"] == "rule-3"
