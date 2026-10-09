"""Centrally clocked workflows have exactly one clock: the automation dispatcher.

A leftover Hatchet cron trigger fires at the same instant as the central
dispatch and, under CANCEL_IN_PROGRESS, cancelled the real run (the model
enrichment sync saved nothing on 2026-10-08 and 2026-10-09).
"""

from __future__ import annotations

import pytest
from hatchet_sdk import ConcurrencyLimitStrategy

from app.services.automation_dispatch import _hatchet_task
from app.services.workflow_schedule_registry import SCHEDULE_DEFINITIONS


@pytest.mark.parametrize("schedule_id", [schedule.schedule_id for schedule in SCHEDULE_DEFINITIONS])
def test_central_schedule_is_dispatchable_without_a_hatchet_cron(schedule_id):
    config = _hatchet_task(schedule_id)._workflow.config
    assert config.on_crons == []
    for concurrency in config.concurrency if isinstance(config.concurrency, list) else [config.concurrency]:
        if concurrency is not None:
            assert concurrency.limit_strategy == ConcurrencyLimitStrategy.CANCEL_NEWEST
