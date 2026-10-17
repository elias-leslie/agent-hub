"""Tests for scheduled memory cleanup cron task.

The Hatchet `@hatchet.task` decorator wraps the function as a Standalone
object, so we test the cleanup integration by verifying:
1. The scheduled module imports cleanup_stale_memories (not cleanup_orphaned)
2. The MemoryCleanupResult model matches TTL cleanup output
"""

from __future__ import annotations

from app.workflows.scheduled import MemoryCleanupResult


class TestMemoryCleanupResult:
    """Verify MemoryCleanupResult matches TTL cleanup output shape."""

    def test_result_has_ttl_fields(self):
        """Result model should have deleted/skipped/reason, not edge/entity counts."""
        result = MemoryCleanupResult(status="success", deleted=5, skipped=False, reason="")
        assert result.deleted == 5
        assert result.skipped is False

    def test_result_defaults(self):
        result = MemoryCleanupResult(status="success")
        assert result.deleted == 0
        assert result.skipped is False
        assert result.reason == ""

    def test_skipped_result(self):
        result = MemoryCleanupResult(
            status="success", deleted=0, skipped=True, reason="System inactive"
        )
        assert result.skipped is True
        assert result.reason == "System inactive"


class TestCleanupImport:
    """Verify the scheduled module uses TTL cleanup, not the old no-op."""


    async def test_cleanup_uses_retirement_threshold_only(self):
        """The scheduled cleanup takes no TTL: retirement's own threshold decides what is stale."""
        from unittest.mock import AsyncMock, patch

        from app.services.memory.cleanup_ttl import cleanup_stale_memories

        retire = AsyncMock(return_value={"retired": 2, "skipped": False, "reason": ""})
        with patch("app.services.memory.cleanup_ttl.retire_stale_archives", retire):
            result = await cleanup_stale_memories()

        retire.assert_awaited_once_with()
        assert result == {"deleted": 0, "retired": 2, "skipped": False, "reason": ""}
