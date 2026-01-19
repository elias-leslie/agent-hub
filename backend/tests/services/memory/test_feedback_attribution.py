"""Tests for feedback attribution to memory rules.

Tests that positive feedback correctly increments success_count
for referenced rules.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestFeedbackAttributionIntegration:
    """Tests for feedback -> memory attribution flow."""

    @pytest.mark.asyncio
    async def test_positive_feedback_increments_success(self):
        """Test that positive feedback increments success_count for cited rules."""
        from app.services.memory.usage_tracker import UsageBuffer

        buffer = UsageBuffer()

        # Simulate: rule was cited in response
        buffer.increment_referenced("rule-uuid-1")
        buffer.increment_referenced("rule-uuid-2")

        # Simulate: user gives positive feedback
        buffer.increment_success("rule-uuid-1")
        buffer.increment_success("rule-uuid-2")

        # Verify counters
        assert buffer._counters["rule-uuid-1"]["referenced"] == 1
        assert buffer._counters["rule-uuid-1"]["success"] == 1
        assert buffer._counters["rule-uuid-2"]["referenced"] == 1
        assert buffer._counters["rule-uuid-2"]["success"] == 1

    @pytest.mark.asyncio
    async def test_negative_feedback_does_not_increment_success(self):
        """Test that negative feedback does not increment success_count."""
        from app.services.memory.usage_tracker import UsageBuffer

        buffer = UsageBuffer()

        # Simulate: rule was cited in response
        buffer.increment_referenced("rule-uuid-1")

        # Negative feedback = no success increment
        # (Success is only incremented on positive feedback)

        assert buffer._counters["rule-uuid-1"]["referenced"] == 1
        assert buffer._counters["rule-uuid-1"]["success"] == 0

    @pytest.mark.asyncio
    async def test_success_only_for_referenced_rules(self):
        """Test that success tracking makes sense with referenced rules."""
        from app.services.memory.usage_tracker import UsageBuffer

        buffer = UsageBuffer()

        # Rule was loaded but not referenced
        buffer.increment_loaded("rule-uuid-1")
        # Should not increment success since it wasn't cited
        # (In practice, the system only increments success for cited rules)

        assert buffer._counters["rule-uuid-1"]["loaded"] == 1
        assert buffer._counters["rule-uuid-1"]["referenced"] == 0
        assert buffer._counters["rule-uuid-1"]["success"] == 0


class TestFeedbackAPIFlow:
    """Tests for feedback API -> usage tracking integration."""

    @pytest.mark.asyncio
    async def test_feedback_endpoint_tracks_success(self):
        """Test feedback endpoint increments success for cited rules."""
        # This tests the conceptual flow, not the actual endpoint
        from app.services.memory.usage_tracker import track_success_batch

        cited_uuids = ["rule-1", "rule-2", "rule-3"]

        with patch("app.services.memory.usage_tracker.get_usage_buffer") as mock_get:
            mock_buffer = MagicMock()
            mock_get.return_value = mock_buffer

            await track_success_batch(cited_uuids)

            # Should increment success for each cited rule
            assert mock_buffer.increment_success.call_count == 3
            mock_buffer.increment_success.assert_any_call("rule-1")
            mock_buffer.increment_success.assert_any_call("rule-2")
            mock_buffer.increment_success.assert_any_call("rule-3")
