"""Retired maintenance dispatch cannot create or reconcile tasks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services.context_maintenance import dispatch_technical_work, reconcile_technical_work


@pytest.mark.asyncio
async def test_technical_work_dispatch_is_unavailable_without_io() -> None:
    db = AsyncMock()
    with pytest.raises(HTTPException) as raised:
        await dispatch_technical_work(db, SimpleNamespace(id="historical-item"), reason="old handoff")
    assert raised.value.status_code == 410
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_technical_work_reconciliation_is_unavailable_without_io() -> None:
    db = AsyncMock()
    with pytest.raises(HTTPException) as raised:
        await reconcile_technical_work(db)
    assert raised.value.status_code == 410
    db.execute.assert_not_awaited()
