from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.services.context_maintenance_actions import MaintenanceRequest, handle_maintenance
from app.services.context_maintenance_work_product import verify_work_product
from app.services.context_policy import semantic_hash
from app.services.runtime_context import CanonicalContextDeliveryRequest


def _context() -> CanonicalContextDeliveryRequest:
    return CanonicalContextDeliveryRequest(
        consumer_surface="agent_runtime",
        agent_slug="memory-curator",
        project_id="agent-hub",
    )


def _row(*, state: str = "resolved", resolution: dict | None = None) -> SimpleNamespace:
    source = {"source_type": "prompt", "source_id": "prompt-a", "revision": "rev-1"}
    request_key = "maintenance-1:generation-2"
    receipt = {
        "id": "task-1",
        "status": "pending",
        "project_id": "agent-hub",
        "external_origin": "agent-hub-context-maintenance",
        "external_request_key": request_key,
        "external_payload_digest": "sha256:payload",
    }
    context = _context().model_dump()
    actual_resolution = resolution or {
        "verification": "canonical_generation",
        "required_policy": {"state": "complete"},
        "verified_sources": [source],
    }
    event = SimpleNamespace(
        id="event-1",
        payload={
            "item_id": "item-1",
            "action": "apply" if state == "resolved" else "dismiss",
            "state": state,
            "version": 3,
            "sources": [source],
            "evidence": {"receipt": receipt, "resolution": actual_resolution},
        },
    )
    return SimpleNamespace(
        id="item-1",
        version=3,
        state=state,
        context=context,
        sources=[source],
        detail={
            "generation": 2,
            "technical_work": {
                "task_id": "task-1",
                "external_request_key": request_key,
                "generation": 2,
                "receipt": receipt,
            },
        },
        resolution=actual_resolution,
        event=event,
    )


def _db(row: SimpleNamespace) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value = [row.event]
    db.execute.return_value = result
    db.get.return_value = None
    return db


async def _verify(row: SimpleNamespace, **overrides):
    db = _db(row)
    with (
        patch(
            "app.services.context_maintenance_work_product.get_source",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "app.services.context_maintenance_work_product.source_revision",
            return_value="rev-1",
        ),
        patch(
            "app.services.context_maintenance_work_product.build_canonical_context_delivery",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    status="ok",
                    payload_hash="hash-1",
                    required_policy=SimpleNamespace(state="complete"),
                )
            ),
        ),
    ):
        return await verify_work_product(
            db,
            row,
            task_id=overrides.get("task_id", "task-1"),
            external_request_key=overrides.get("external_request_key", "maintenance-1:generation-2"),
            external_payload_digest=overrides.get("external_payload_digest", "sha256:payload"),
            generation=overrides.get("generation", 2),
        )


@pytest.mark.asyncio
async def test_verify_work_product_returns_compact_verified_receipt() -> None:
    result = await _verify(_row())

    assert result["verified"] is True
    assert result["item_id"] == "item-1"
    assert result["event_id"] == "event-1"
    assert result["verified_sources"] == [{"source_type": "prompt", "source_id": "prompt-a", "revision": "rev-1"}]
    assert set(result) == {
        "verified", "reason", "item_id", "item_version", "task_id", "external_request_key",
        "external_payload_digest", "state", "change_id", "event_id", "verified_sources",
        "payload_hash", "verification",
    }


@pytest.mark.asyncio
async def test_verify_work_product_rejects_exact_binding_mismatch() -> None:
    result = await _verify(_row(), external_request_key="wrong-key")

    assert result["verified"] is False
    assert "receipt" in result["reason"]


@pytest.mark.asyncio
async def test_verify_work_product_rejects_stale_source_revision() -> None:
    row = _row()
    db = _db(row)
    with (
        patch(
            "app.services.context_maintenance_work_product.get_source",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "app.services.context_maintenance_work_product.source_revision",
            return_value="rev-2",
        ),
    ):
        result = await verify_work_product(
            db,
            row,
            task_id="task-1",
            external_request_key="maintenance-1:generation-2",
            external_payload_digest="sha256:payload",
            generation=2,
        )

    assert result["verified"] is False
    assert "stale" in result["reason"]


@pytest.mark.asyncio
async def test_verify_work_product_rejects_false_claimed_resolution() -> None:
    row = _row(resolution={"verified_sources": [{"source_type": "prompt", "source_id": "prompt-a", "revision": "rev-1"}]})

    result = await _verify(row)

    assert result["verified"] is False
    assert "canonical generation" in result["reason"]


@pytest.mark.asyncio
async def test_verify_work_product_rejects_empty_verified_sources() -> None:
    row = _row()
    row.resolution["verified_sources"] = []

    result = await _verify(row)

    assert result["verified"] is False
    assert "source evidence" in result["reason"]


@pytest.mark.asyncio
async def test_verify_work_product_rejects_generation_mismatch() -> None:
    result = await _verify(_row(), generation=1)

    assert result["verified"] is False
    assert "receipt" in result["reason"]


@pytest.mark.asyncio
async def test_verify_work_product_rejects_missing_immutable_receipt() -> None:
    row = _row()
    row.event.payload["sources"] = []

    result = await _verify(row)

    assert result["verified"] is False
    assert "receipt" in result["reason"]


async def _changed_row() -> tuple[SimpleNamespace, SimpleNamespace]:
    before = {"source_type": "prompt", "source_id": "prompt-a", "name": "old"}
    current_revision = "sha256:current"
    source = {"source_type": "prompt", "source_id": "prompt-a", "revision": current_revision}
    row = _row()
    row.sources = [{**source, "revision": "sha256:" + semantic_hash(before)}]
    row.resolution["verified_sources"] = [source]
    row.event.payload["sources"] = list(row.sources)
    row.event.payload["evidence"]["resolution"] = row.resolution
    change = SimpleNamespace(
        id="change-1",
        kind="change",
        payload={
            "context": _context().model_dump(),
            "changes": [{"before": before, "after": {**before, "name": "new"}, "after_revision": current_revision}],
        },
    )
    row.resolution["change_id"] = "change-1"
    row.event.payload["evidence"]["resolution"] = row.resolution
    return row, change


@pytest.mark.asyncio
async def test_verify_work_product_accepts_exact_change_before_after_receipt() -> None:
    row, change = await _changed_row()
    db = _db(row)
    db.get.return_value = change
    with (
        patch("app.services.context_maintenance_work_product.get_source", new=AsyncMock(return_value=SimpleNamespace())),
        patch("app.services.context_maintenance_work_product.source_revision", return_value="sha256:current"),
        patch(
            "app.services.context_maintenance_work_product.build_canonical_context_delivery",
            new=AsyncMock(return_value=SimpleNamespace(status="ok", payload_hash="hash-1", required_policy=SimpleNamespace(state="complete"))),
        ),
    ):
        result = await verify_work_product(
            db,
            row,
            task_id="task-1",
            external_request_key="maintenance-1:generation-2",
            external_payload_digest="sha256:payload",
            generation=2,
        )

    assert result["verified"] is True
    assert result["change_id"] == "change-1"


@pytest.mark.asyncio
async def test_verify_work_product_rejects_wrong_change_after_revision() -> None:
    row, change = await _changed_row()
    change.payload["changes"][0]["after_revision"] = "sha256:wrong"
    db = _db(row)
    db.get.return_value = change
    with patch(
        "app.services.context_maintenance_work_product.get_source",
        new=AsyncMock(return_value=SimpleNamespace()),
    ), patch(
        "app.services.context_maintenance_work_product.source_revision",
        return_value="sha256:current",
    ):
        result = await verify_work_product(
            db,
            row,
            task_id="task-1",
            external_request_key="maintenance-1:generation-2",
            external_payload_digest="sha256:payload",
            generation=2,
        )

    assert result["verified"] is False
    assert "stale" in result["reason"]


def test_verify_work_request_is_strict_and_requires_work_fields_at_runtime() -> None:
    request = MaintenanceRequest(action="verify_work", context=_context())

    assert request.task_id is None
    with pytest.raises(ValidationError):
        MaintenanceRequest.model_validate({"action": "verify_work", "context": _context().model_dump(), "unexpected": True})


@pytest.mark.asyncio
async def test_authenticated_task_project_can_verify_against_recorded_delivery_context() -> None:
    db = AsyncMock()
    row = SimpleNamespace(id="item-1")
    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = row
    db.execute.return_value = query_result
    request = MaintenanceRequest(
        action="verify_work",
        context=_context(),
        item_id="item-1",
        task_id="task-1",
        external_request_key="maintenance-1:generation-2",
        external_payload_digest="sha256:payload",
        generation=2,
    )
    expected = {"verified": True, "verification": "canonical_generation"}

    with (
        patch(
            "app.services.context_maintenance_actions.relevant_items",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.context_maintenance_work_product.verify_work_product",
            new=AsyncMock(return_value=expected),
        ) as verify,
    ):
        result = await handle_maintenance(
            db,
            request,
            actor="api:sf-key",
            caller_service_client={
                "id": "summitflow",
                "allowed_projects": '["summitflow", "agent-hub"]',
            },
        )

    assert result == expected
    verify.assert_awaited_once_with(
        db,
        row,
        task_id="task-1",
        external_request_key="maintenance-1:generation-2",
        external_payload_digest="sha256:payload",
        generation=2,
    )


@pytest.mark.asyncio
async def test_unscoped_caller_cannot_cross_context_verify_work() -> None:
    db = AsyncMock()
    visible_row = SimpleNamespace(id="item-1")
    request = MaintenanceRequest(
        action="verify_work",
        context=_context(),
        item_id="item-1",
        task_id="task-1",
        external_request_key="maintenance-1:generation-2",
        external_payload_digest="sha256:payload",
        generation=2,
    )

    with patch(
        "app.services.context_maintenance_actions.relevant_items",
        new=AsyncMock(return_value=[visible_row]),
    ) as relevant, pytest.raises(HTTPException) as raised:
        await handle_maintenance(
            db,
            request,
            actor="api:other",
            caller_service_client={"id": "other", "allowed_projects": '["other"]'},
        )

    assert raised.value.status_code == 404
    relevant.assert_not_awaited()
    db.execute.assert_not_awaited()
