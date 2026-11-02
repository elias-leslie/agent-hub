from datetime import UTC, datetime

from app.services.memory.memory_models import MemoryScope, MemorySource
from app.services.memory.timeline_service import _memory_to_episode


def test_timeline_episode_builds_for_a_plain_memory_row():
    # Regression: the timeline hardcoded source="text", which MemorySource rejects,
    # so /api/memory/timeline failed validation on every memory.
    ep = _memory_to_episode({"uuid": "m1", "name": "n", "content": "c", "tier": "reference", "valid_at": datetime(2026, 11, 2, tzinfo=UTC)}, MemoryScope.GLOBAL, None)
    assert ep.source is MemorySource.SYSTEM
    assert ep.uuid == "m1"
