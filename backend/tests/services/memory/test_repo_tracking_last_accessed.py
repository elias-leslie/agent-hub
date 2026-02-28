"""Tests for increment_referenced updating last_accessed_at."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.memory._repo_tracking import TrackingRepository


class TestIncrementReferencedLastAccessed:
    """Verify increment_referenced sets last_accessed_at alongside the count."""

    @pytest.mark.asyncio
    async def test_increment_referenced_sets_last_accessed_at(self):
        """last_accessed_at must be updated when a memory is cited."""
        repo = TrackingRepository()
        uid = uuid4()

        mock_db = AsyncMock()
        await repo.increment_referenced([uid], db=mock_db)

        mock_db.execute.assert_called_once()
        stmt = mock_db.execute.call_args[0][0]
        # Compile the UPDATE statement and check it sets last_accessed_at
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "last_accessed_at" in compiled
        assert "referenced_count" in compiled

    @pytest.mark.asyncio
    async def test_increment_referenced_empty_list(self):
        """Empty list should be a no-op."""
        repo = TrackingRepository()
        mock_db = AsyncMock()
        await repo.increment_referenced([], db=mock_db)
        mock_db.execute.assert_not_called()
