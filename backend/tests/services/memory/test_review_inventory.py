"""Tests for the auditable per-memory review inventory."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.memory._review_agent_prompt import REVIEW_CHECK_KEYS
from app.services.memory.review_inventory import collect_memory_review_inventory


@pytest.mark.asyncio
async def test_collect_memory_review_inventory_requires_all_review_checks() -> None:
    now = datetime.now(UTC)
    complete_checks = {key: "pass" for key in REVIEW_CHECK_KEYS}
    memories = [
        SimpleNamespace(
            id="11111111-1111-1111-1111-111111111111",
            uuid_short="11111111",
            name="Current rule",
            scope="global",
            scope_id=None,
            context_kind="policy",
            tier=1,
            review_status="clean",
            last_reviewed_at=now,
            content="Use the canonical service.",
            metadata_={
                "last_review": {
                    "decision": "keep",
                    "reason": "All checks passed.",
                    "checks": complete_checks,
                    "prompt_migration_required": True,
                    "applied_remediations": ["tags"],
                },
                "compact_status": "not_needed",
            },
        ),
        SimpleNamespace(
            id="22222222-2222-2222-2222-222222222222",
            uuid_short="22222222",
            name="Legacy review",
            scope="project",
            scope_id="agent-hub",
            context_kind="reference",
            tier=3,
            review_status="needs_action",
            last_reviewed_at=now,
            content="Old review without per-check evidence.",
            metadata_={"last_review": {"decision": "retarget", "checks": {}}},
        ),
    ]
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = memories
    mock_db = AsyncMock()
    mock_db.execute.return_value = execute_result

    inventory = await collect_memory_review_inventory(mock_db)

    assert inventory["active_count"] == 2
    assert inventory["review_complete_count"] == 1
    assert inventory["review_incomplete_count"] == 1
    assert inventory["clean_count"] == 1
    assert inventory["needs_action_count"] == 1
    assert inventory["prompt_migration_required_count"] == 1
    assert inventory["items"][0]["checks"] == complete_checks
    assert inventory["items"][0]["applied_remediations"] == ["tags"]
