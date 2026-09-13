"""Receipt recovery crosses the real lookup seam and cannot dispatch a turn."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.complete.endpoints import router
from app.api.complete.native_continuation import lookup_native_receipt
from app.db import get_db
from app.models import NativeContinuationTurn


def stored_receipt(status: str = "completed") -> NativeContinuationTurn:
    return NativeContinuationTurn(
        session_id="fixture-session", generation=3, request_id="fixture-request",
        payload_hash="a" * 64, expected_turn=1, accepted_turn=2,
        context_version="fixture-2", instruction_hash="b" * 64, tool_policy_hash="c" * 64,
        runtime_status="active", agent_used="fixture-reader", status=status,
        native_thread_id="fixture-thread", native_turn_id="fixture-turn",
        content='{"result":"fixture only"}', model_used="fixture-model",
        input_tokens=12, cache_read_tokens=4, output_tokens=3, reasoning_tokens=0,
        usage_known=True,
    )


@pytest.fixture
def lookup_db() -> AsyncMock:
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(
        id="fixture-session", client_id="fixture-client", project_id="fixture-project",
        provider_metadata={"native_continuation": {
            "generation": 3, "controller_generation": "fixture-controller", "status": "active",
        }},
    )
    return db


async def lookup(db: AsyncMock, **changes: object):
    values: dict[str, Any] = dict(
        db=db, client_id="fixture-client", session_id="fixture-session",
        project_id="fixture-project", generation=3, request_id="fixture-request",
        controller_generation="fixture-controller",
    )
    values.update(changes)
    return await lookup_native_receipt(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "accepted", "failed", "superseded"])
async def test_receipt_hit_is_lookup_only(lookup_db: AsyncMock, status: str) -> None:
    receipt = stored_receipt(status)
    with (
        patch("app.api.complete.native_continuation._find_receipt", AsyncMock(return_value=receipt)),
        patch("app.api.complete.native_continuation.get_native_runtime_manager") as runtime,
        patch("app.api.complete.native_continuation._canonical_instructions") as context,
    ):
        result = await lookup(lookup_db, expected_turn=1, context_version="fixture-2")
    assert result.status == ("uncertain" if status == "accepted" else status)
    assert (result.completion is not None) == (status == "completed")
    assert (result.accounting is not None) == (status != "accepted")
    if result.accounting:
        assert result.accounting.input_tokens == 12
        assert result.accounting.cache_read_tokens == 4
        assert result.accounting.output_tokens == 3
        assert result.accounting.total_tokens == 15
        assert not hasattr(result.accounting, "content")
    if result.completion:
        assert result.completion.content == receipt.content
        assert result.completion.native_continuation.duplicate is True
        assert result.completion.usage.input_tokens == 12
    runtime.assert_not_called()
    context.assert_not_called()
    lookup_db.add.assert_not_called()
    lookup_db.commit.assert_not_called()
    lookup_db.flush.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_terminal_usage_is_not_reported_as_zero(lookup_db: AsyncMock) -> None:
    receipt = stored_receipt("superseded")
    receipt.usage_known = False
    with patch(
        "app.api.complete.native_continuation._find_receipt",
        AsyncMock(return_value=receipt),
    ):
        result = await lookup(lookup_db)
    assert result.status == "superseded"
    assert result.accounting is None
    assert result.completion is None


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,status", [
    ({"client_id": None}, 401),
    ({"client_id": "another-client"}, 404),
    ({"project_id": "another-project"}, 404),
    ({"generation": 2}, 409),
    ({"controller_generation": "another-controller"}, 409),
])
async def test_identity_mismatch_never_reads_receipt(lookup_db: AsyncMock, changes: dict, status: int) -> None:
    with (
        patch("app.api.complete.native_continuation._find_receipt", AsyncMock()) as find,
        pytest.raises(HTTPException) as raised,
    ):
        await lookup(lookup_db, **changes)
    assert raised.value.status_code == status
    find.assert_not_awaited()
    lookup_db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_missing_session_and_receipt_are_not_recreated(lookup_db: AsyncMock) -> None:
    with patch("app.api.complete.native_continuation._find_receipt", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as raised:
            await lookup(lookup_db)
        assert raised.value.status_code == 404
        lookup_db.get.return_value = None
        with pytest.raises(HTTPException) as raised:
            await lookup(lookup_db)
        assert raised.value.status_code == 404
    lookup_db.add.assert_not_called()
    lookup_db.commit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"expected_turn": 0}, {"context_version": "different"}, {"payload_hash": "d" * 64},
])
async def test_asserted_request_identity_conflicts(lookup_db: AsyncMock, changes: dict) -> None:
    with (
        patch("app.api.complete.native_continuation._find_receipt", AsyncMock(return_value=stored_receipt())),
        pytest.raises(HTTPException) as raised,
    ):
        await lookup(lookup_db, **changes)
    assert raised.value.status_code == 409
    lookup_db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_get_route_returns_exact_receipt_without_completion(lookup_db: AsyncMock) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: lookup_db

    params = dict(session_id="fixture-session", project_id="fixture-project", generation=3,
                  request_id="fixture-request", controller_generation="fixture-controller")
    with (
        patch("app.api.complete.native_continuation._find_receipt", AsyncMock(return_value=stored_receipt())),
        patch("app.api.complete.endpoints.orchestrate_completion") as complete,
        patch("app.api.complete.native_continuation.get_native_runtime_manager") as runtime,
        patch("app.middleware.access_control_auth.get_cached_client", AsyncMock(return_value={
            "id": "fixture-client", "status": "active", "allowed_projects": '["fixture-project"]',
        })),
    ):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://fixture") as client:
            headers = {"X-Agent-Hub-Internal": "agent-hub-internal-v1", "X-Client-Id": "fixture-client"}
            unauthenticated = await client.get("/api/complete/native/receipt", params=params)
            response = await client.get("/api/complete/native/receipt", params=params, headers=headers)
            denied = await client.get("/api/complete/native/receipt", params={**params, "project_id": "other"}, headers=headers)
    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["completion"]["content"] == '{"result":"fixture only"}'
    assert denied.status_code == 403
    complete.assert_not_called()
    runtime.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "superseded"])
async def test_get_route_returns_terminal_accounting_without_content(
    lookup_db: AsyncMock, status: str,
) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: lookup_db
    params = dict(session_id="fixture-session", project_id="fixture-project", generation=3,
                  request_id="fixture-request", controller_generation="fixture-controller")
    with (
        patch("app.api.complete.native_continuation._find_receipt",
              AsyncMock(return_value=stored_receipt(status))),
        patch("app.middleware.access_control_auth.get_cached_client", AsyncMock(return_value={
            "id": "fixture-client", "status": "active", "allowed_projects": '["fixture-project"]',
        })),
    ):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://fixture") as client:
            response = await client.get(
                "/api/complete/native/receipt", params=params,
                headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1",
                         "X-Client-Id": "fixture-client"},
            )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == status
    assert body["completion"] is None
    assert body["accounting"] == {
        "model_used": "fixture-model", "agent_used": "fixture-reader",
        "input_tokens": 12, "cache_read_tokens": 4, "output_tokens": 3,
        "reasoning_tokens": 0, "total_tokens": 15, "usage_known": True,
    }
    assert "content" not in body["accounting"]
