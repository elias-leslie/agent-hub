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

    def test_scheduled_module_references_ttl_cleanup(self):
        """The memory_cleanup_task source should reference cleanup_stale_memories."""
        import inspect

        import app.workflows.scheduled as scheduled_mod

        # Get the source of the module
        source = inspect.getsource(scheduled_mod)
        assert "cleanup_stale_memories" in source
        assert "cleanup_orphaned" not in source
