"""Automatic context recovery is retired."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services.context_maintenance_worker import _recover_pending, run_context_maintenance


@pytest.mark.asyncio
async def test_context_recovery_is_unavailable_without_database_io() -> None:
    db = AsyncMock()
    for operation in (_recover_pending(db), run_context_maintenance(db, batch_limit=1)):
        with pytest.raises(HTTPException) as raised:
            await operation
        assert raised.value.status_code == 410
    db.execute.assert_not_awaited()
