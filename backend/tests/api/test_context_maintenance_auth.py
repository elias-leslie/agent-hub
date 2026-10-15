"""verify_work is retired with the curator: every caller gets 410, secret or not."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.context_management import maintenance
from app.services.context_maintenance_actions import MaintenanceRequest
from app.services.runtime_context import CanonicalContextDeliveryRequest


def _payload() -> MaintenanceRequest:
    return MaintenanceRequest(
        action="verify_work",
        context=CanonicalContextDeliveryRequest(
            consumer_surface="agent_runtime",
            agent_slug="memory-curator",
            project_id="agent-hub",
        ),
        item_id="item-1",
        task_id="task-1",
        external_request_key="item-1:generation-2",
        external_payload_digest="sha256:payload",
        generation=2,
    )


@pytest.mark.asyncio
async def test_verify_work_route_is_retired() -> None:
    db = AsyncMock()
    with pytest.raises(HTTPException) as raised:
        await maintenance(_payload(), db)

    assert raised.value.status_code == 410
    db.execute.assert_not_awaited()
    db.rollback.assert_awaited_once()
