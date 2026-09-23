"""Legacy import cannot revive a retired memory review schedule."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import automations


def _rows(rows: list[SimpleNamespace]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("review_job_type", ["memory_review", "agent_turn"])
async def test_legacy_reimport_keeps_review_disabled_and_preserves_other_jobs(review_job_type: str) -> None:
    due = datetime(2026, 9, 24, 4, 17, tzinfo=UTC)
    last = datetime(2026, 9, 23, 4, 17, tzinfo=UTC)
    review = SimpleNamespace(
        source_ref="persona:review", clock_owner="legacy",
        config={"payload_type": "memory_review"}, enabled=False,
        next_run_at=None, last_run_at=None, run_count=0, max_runs=None,
    )
    normal = SimpleNamespace(
        source_ref="persona:normal", clock_owner="legacy",
        config={"payload_type": "agent_turn"}, enabled=False,
        next_run_at=None, last_run_at=None, run_count=0, max_runs=None,
    )
    jobs = [
        SimpleNamespace(id="review", payload_type=review_job_type, enabled=True,
                        next_run_at=due, last_run_at=last, run_count=136, max_runs=None),
        SimpleNamespace(id="normal", payload_type="agent_turn", enabled=True,
                        next_run_at=due, last_run_at=last, run_count=7, max_runs=20),
    ]
    db = AsyncMock()
    db.add = MagicMock()
    persona_result = MagicMock()
    persona_result.scalar_one_or_none.return_value = None
    db.execute.side_effect = [_rows([]), _rows([review, normal]), persona_result, _rows(jobs)]
    db.get.return_value = object()

    with (
        patch.object(automations, "EXTERNAL_WORKFLOWS", ()),
        patch.object(automations, "SCHEDULE_DEFINITIONS", ()),
        patch("app.workflows._heartbeat_redis.get_last_run_info", new=AsyncMock(return_value=None)),
    ):
        await automations.import_agent_hub_legacy(db)

    assert review.enabled is False
    assert review.next_run_at is None
    assert review.last_run_at == last
    assert review.run_count == 136
    assert normal.enabled is True
    assert normal.next_run_at == due
    assert normal.last_run_at == last
    assert normal.run_count == 7
    assert normal.max_runs == 20
    db.add.assert_not_called()
