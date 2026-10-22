"""Tests for the external cost ingest endpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.api.cost_ingest import CostIngestRequest, ingest_cost, ingest_session_id
from app.models import CostLog
from app.models import Session as DBSession


def _request(allowed_projects: str | None = '["nightshift"]') -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/api/analytics/costs/ingest", "headers": []})
    request.state.client_id = "client-nightshift"
    request.state.allowed_projects = allowed_projects
    request.state.request_source = "nightshift"
    request.state.is_internal = False
    return request


def _body(**over: object) -> CostIngestRequest:
    data: dict[str, object] = {
        "project_id": "nightshift", "provider": "typesafe", "model": "jev-1.13.0", "input_tokens": 1200,
        "output_tokens": 0, "cost_usd": 0.0504, "billing_kind": "metered", "source": "nightshift.decide",
        "idempotency_key": "nightshift:abc123def456", "occurred_at": datetime.now(UTC) - timedelta(hours=1),
    }
    data.update(over)
    return CostIngestRequest.model_validate(data)


def _db(existing: DBSession | None = None, permission: bool = True) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(return_value=1 if permission else None)
    db.get = AsyncMock(return_value=existing)
    return db


@pytest.mark.asyncio
async def test_creates_metered_session_and_cost_log() -> None:
    db = _db()
    body = _body()
    out = await ingest_cost(body, _request(), Response(), db)

    assert out.status == "created"
    assert out.session_id == ingest_session_id("nightshift", body.idempotency_key)
    added = [c.args[0] for c in db.add.call_args_list]
    session = next(a for a in added if isinstance(a, DBSession))
    log = next(a for a in added if isinstance(a, CostLog))
    assert session.project_id == "nightshift" and session.client_id == "client-nightshift"
    assert session.request_source == "nightshift.decide" and session.created_at == body.occurred_at
    assert log.billing_mode == "metered" and log.cost_usd == pytest.approx(0.0504)
    assert log.created_at == body.occurred_at
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_with_same_payload_is_duplicate() -> None:
    body = _body()
    existing = MagicMock(spec=DBSession, project_id="nightshift",
                         provider_metadata={"cost_ingest": {"payload_hash": body.payload_hash()}})
    db = _db(existing)
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(
        return_value=MagicMock(id=7, billing_mode="metered", cost_usd=0.0504))))
    response = Response()
    out = await ingest_cost(body, _request(), response, db)

    assert out.status == "duplicate" and out.cost_log_id == 7
    assert response.status_code == 200
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_same_key_different_payload_conflicts() -> None:
    existing = MagicMock(spec=DBSession, project_id="nightshift",
                         provider_metadata={"cost_ingest": {"payload_hash": "other"}})
    with pytest.raises(HTTPException) as exc:
        await ingest_cost(_body(), _request(), Response(), _db(existing))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_insert_race_returns_duplicate() -> None:
    body = _body()
    existing = MagicMock(spec=DBSession, project_id="nightshift",
                         provider_metadata={"cost_ingest": {"payload_hash": body.payload_hash()}})
    db = _db()
    db.get = AsyncMock(side_effect=[None, existing])
    db.commit = AsyncMock(side_effect=IntegrityError("insert", {}, Exception("dup")))
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    out = await ingest_cost(body, _request(), Response(), db)
    assert out.status == "duplicate"
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_requires_project_access() -> None:
    db = _db()
    with pytest.raises(HTTPException) as exc:
        await ingest_cost(_body(), _request('["other"]'), Response(), db)
    assert exc.value.status_code == 403
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_requires_registered_project() -> None:
    with pytest.raises(HTTPException) as exc:
        await ingest_cost(_body(), _request(), Response(), _db(permission=False))
    assert exc.value.status_code == 404


def test_cash_only_for_metered_and_time_window() -> None:
    with pytest.raises(ValidationError):
        _body(billing_kind="local", cost_usd=0.1)
    assert _body(billing_kind="local", cost_usd=0.0).billing_kind == "local"
    with pytest.raises(ValidationError):
        _body(occurred_at=datetime(2026, 1, 1))  # naive
    with pytest.raises(ValidationError):
        _body(occurred_at=datetime.now(UTC) + timedelta(days=1))
    with pytest.raises(ValidationError):
        _body(idempotency_key="bad key with spaces")


def test_session_id_is_stable_and_project_scoped() -> None:
    assert ingest_session_id("nightshift", "k" * 10) == ingest_session_id("nightshift", "k" * 10)
    assert ingest_session_id("nightshift", "k" * 10) != ingest_session_id("other", "k" * 10)


@pytest.mark.asyncio
async def test_subscription_call_without_list_price_is_priced_from_its_tokens() -> None:
    db = _db()
    body = _body(model="claude-opus-5-5", cost_usd=0.0, billing_kind="subscription", input_tokens=10,
                 output_tokens=2571, cache_read_tokens=88296, cache_write_tokens=26521)
    await ingest_cost(body, _request(), Response(), db)

    log = next(c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], CostLog))
    assert log.cost_usd == 0.0 and log.api_equiv_usd == pytest.approx(0.2813, abs=0.001)


@pytest.mark.asyncio
async def test_codex_subscription_ingest_uses_its_catalog_rate() -> None:
    from app.services.subscription_accounting.rates import subscription_call_value

    db = _db()
    body = _body(provider="codex", model="gpt-6.1-sol", cost_usd=0, billing_kind="subscription",
                 input_tokens=17950, output_tokens=244)
    await ingest_cost(body, _request(), Response(), db)
    log = next(call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], CostLog))
    expected = subscription_call_value(body.model, input_tokens=body.input_tokens, output_tokens=body.output_tokens)
    assert expected is not None and expected.api_equiv_usd is not None
    assert log.api_equiv_usd == expected.api_equiv_usd


@pytest.mark.asyncio
async def test_subscription_retry_fills_only_missing_list_price() -> None:
    body = _body(provider="codex", model="gpt-6.1-sol", cost_usd=0, billing_kind="subscription")
    existing = MagicMock(spec=DBSession, project_id="nightshift",
                         provider_metadata={"cost_ingest": {"payload_hash": body.payload_hash()}})
    row = CostLog(id=42, session_id="retained", model=body.model, input_tokens=1200, output_tokens=0,
                  billing_mode="subscription", cost_usd=0, api_equiv_usd=None)
    db = _db(existing)
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=row))
    for _ in range(2):
        result = await ingest_cost(body, _request(), Response(), db)
        assert result.status == "duplicate" and result.cost_log_id == 42
    assert row.api_equiv_usd is not None
    assert row.cost_usd == 0
    db.commit.assert_awaited_once()
    db.add.assert_not_called()
