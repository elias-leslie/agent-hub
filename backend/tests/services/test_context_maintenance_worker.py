"""Routine findings are corrected directly using the existing change history."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.services.context_maintenance_worker import _recover_pending


@pytest.mark.asyncio
async def test_recovery_applies_directly_and_skips_superseded_sibling():
    first = SimpleNamespace(id="first", state="pending", claim_owner=None)
    sibling = SimpleNamespace(id="sibling", state="pending", claim_owner=None)
    db = AsyncMock()
    rows = MagicMock()
    rows.scalars.return_value = [first, sibling]
    db.execute.return_value = rows

    async def reconcile(_db):
        if first.state == "resolved":
            sibling.state = "superseded"

    async def repair(_db, item, context):
        item.state = "resolved"
        return {"model_calls": 1, "action": {"state": "resolved", "receipt_id": "before-after-change"}}

    with (
        patch("app.services.context_maintenance_reconcile.reconcile_maintenance", new=AsyncMock(side_effect=reconcile)),
        patch("app.services.context_maintenance_worker.review_context", return_value=object()),
        patch("app.services.context_maintenance_recovery.recover_item", new=AsyncMock(side_effect=repair)) as recover,
        patch("app.services.context_maintenance_tasks.dispatch_technical_work", new=AsyncMock()) as tasks,
    ):
        result = await _recover_pending(db, review_ids=["just-completed-review"])

    recover.assert_awaited_once()
    tasks.assert_not_awaited()
    assert result[0]["action"]["receipt_id"] == "before-after-change"
    assert first.state == "resolved"
    assert sibling.state == "superseded"
    assert db.execute.await_args is not None
    query = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "?| ARRAY[" in query
