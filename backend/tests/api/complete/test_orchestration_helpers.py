from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.complete.orchestration_helpers import execute_and_respond


@pytest.mark.asyncio
async def test_execute_and_respond_rolls_back_and_handles_cancelled_error() -> None:
    request = SimpleNamespace(
        trace_id=None,
        agent_slug="persona",
    )
    db = AsyncMock()

    with patch(
        "app.api.complete.orchestration_helpers.execute_completion",
        new_callable=AsyncMock,
        side_effect=asyncio.CancelledError("sdk cancelled"),
    ), patch(
        "app.api.complete.orchestration_helpers.handle_completion_error",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=500, detail="Completion cancelled unexpectedly."),
    ) as handle_error, pytest.raises(HTTPException) as exc_info:
        await execute_and_respond(
            request=request,
            resolved_model="claude-sonnet-4-6",
            provider="claude",
            resolved_agent=None,
            messages_dict=[{"role": "user", "content": "hello"}],
            all_messages=[],
            is_agentic=True,
            db=db,
            session=None,
            session_id="sess-123",
            client_id=None,
            source=None,
            skip_cache=False,
            ctx_info=None,
            memory_facts=0,
            loaded_uuids_in=[],
            agent_used="persona",
            is_new_session=True,
            http_request=None,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Completion cancelled unexpectedly."
    db.rollback.assert_awaited_once()
    handle_error.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_completion_error_maps_cancelled_error_to_http_500() -> None:
    from app.api.complete.error_handlers import handle_completion_error

    with patch(
        "app.api.complete.error_handlers._notify_error",
        new_callable=AsyncMock,
    ) as notify_error, pytest.raises(HTTPException) as exc_info:
        await handle_completion_error(
            asyncio.CancelledError("sdk cancelled"),
            session_id="sess-123",
            db=AsyncMock(),
            agent_id="persona",
            model_used="claude-sonnet-4-6",
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Completion cancelled unexpectedly."
    notify_error.assert_awaited_once()
