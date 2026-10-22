"""External cost ingest.

POST /analytics/costs/ingest  record one model call that an external client made and paid for outside Agent Hub.

Each entry becomes a lightweight completed session plus one cost_logs row, so metered rows count toward metered cash
in /analytics/costs/accounting and the dashboard. The idempotency key fixes the session id: a retry of the same entry
returns the stored row, and a different payload under the same key is a conflict.

Ingested spend is not charged to the project's completion budget: that budget gates Agent Hub-routed completions,
and the external client enforces its own caps.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access_control_helpers import require_project_access
from app.db import get_db
from app.models import CostLog, ProjectPermission
from app.models import Session as DBSession
from app.models.field_lengths import EXTERNAL_ID_MAX_LENGTH
from app.services.subscription_accounting.rates import subscription_call_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])

# Fixed namespace: the session id for (project_id, idempotency_key) is stable across restarts and hosts.
_INGEST_NAMESPACE = uuid.UUID("5b0c7e2a-3f1d-4c55-9a8e-6d2f0b1c4e7a")
_MAX_AGE = timedelta(days=400)
_MAX_SKEW = timedelta(minutes=10)


class CostIngestRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=100)
    provider: str = Field(..., min_length=1, max_length=20, description="Who billed the call, e.g. typesafe")
    model: str = Field(..., min_length=1, max_length=100)
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)
    cache_read_tokens: int = Field(0, ge=0)
    cache_write_tokens: int = Field(0, ge=0)
    cost_usd: float = Field(..., ge=0, le=1000, description="Cash paid for this call; 0 unless billing_kind is metered")
    billing_kind: Literal["metered", "subscription", "local"] = "metered"
    api_equiv_usd: float | None = Field(None, ge=0, description="List-price value; never counted as cash")
    source: str = Field(..., min_length=1, max_length=100, description="Calling component, e.g. nightshift.decide")
    idempotency_key: str = Field(..., min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:\-]+$")
    occurred_at: datetime | None = Field(None, description="When the call happened (timezone required); default now")
    external_id: str | None = Field(None, max_length=EXTERNAL_ID_MAX_LENGTH)

    @model_validator(mode="after")
    def _check(self) -> CostIngestRequest:
        if self.billing_kind != "metered" and self.cost_usd > 0:
            raise ValueError("cost_usd must be 0 unless billing_kind is metered")
        if self.occurred_at is not None:
            if self.occurred_at.tzinfo is None:
                raise ValueError("occurred_at needs a timezone")
            now = datetime.now(UTC)
            if self.occurred_at > now + _MAX_SKEW or self.occurred_at < now - _MAX_AGE:
                raise ValueError("occurred_at is outside the accepted window")
        return self

    def payload_hash(self) -> str:
        body = self.model_dump(mode="json", exclude={"occurred_at"})
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


class CostIngestResponse(BaseModel):
    status: Literal["created", "duplicate"]
    session_id: str
    cost_log_id: int | None
    billing_kind: str
    cost_usd: float


def ingest_session_id(project_id: str, idempotency_key: str) -> str:
    return str(uuid.uuid5(_INGEST_NAMESPACE, f"{project_id}\n{idempotency_key}"))


def _api_equiv(body: CostIngestRequest) -> float | None:
    """List-price value for a subscription call; priced here (1-hour cache writes, like Nightshift) when missing."""
    if body.api_equiv_usd is not None or body.billing_kind != "subscription":
        return body.api_equiv_usd
    value = subscription_call_value(
        body.model, input_tokens=body.input_tokens, output_tokens=body.output_tokens,
        cache_read=body.cache_read_tokens or 0, cache_write=body.cache_write_tokens or 0,
    )
    return value.api_equiv_usd if value is not None else None


async def _existing(db: AsyncSession, body: CostIngestRequest, session_id: str) -> CostIngestResponse | None:
    session = await db.get(DBSession, session_id)
    if session is None:
        return None
    meta = (session.provider_metadata or {}).get("cost_ingest") or {}
    if session.project_id != body.project_id or meta.get("payload_hash") != body.payload_hash():
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "message": "This idempotency key was used for a different entry."},
        )
    row = (await db.execute(select(CostLog).where(CostLog.session_id == session_id).limit(1))).scalar_one_or_none()
    if row is not None and row.billing_mode == "subscription" and row.api_equiv_usd is None:
        value = _api_equiv(body)
        if value is not None:
            row.api_equiv_usd = value
            await db.commit()
    return CostIngestResponse(
        status="duplicate", session_id=session_id, cost_log_id=row.id if row else None,
        billing_kind=row.billing_mode if row else body.billing_kind, cost_usd=float(row.cost_usd) if row else body.cost_usd,
    )


@router.post("/costs/ingest", response_model=CostIngestResponse, status_code=201)
async def ingest_cost(
    body: CostIngestRequest,
    http_request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CostIngestResponse:
    """Record one externally billed model call; safe to retry with the same idempotency key."""
    require_project_access(http_request, body.project_id)
    if await db.scalar(select(ProjectPermission.id).where(ProjectPermission.project_id == body.project_id)) is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "project_not_registered", "message": f"No project permission for '{body.project_id}'."},
        )

    session_id = ingest_session_id(body.project_id, body.idempotency_key)
    dup = await _existing(db, body, session_id)
    if dup is not None:
        response.status_code = 200
        return dup

    at = body.occurred_at or datetime.now(UTC)
    client_id = getattr(http_request.state, "client_id", None)
    db.add(
        DBSession(
            id=session_id, project_id=body.project_id, provider=body.provider, model=body.model, status="completed",
            session_type="completion", external_id=body.external_id or body.idempotency_key[:EXTERNAL_ID_MAX_LENGTH],
            client_id=client_id if isinstance(client_id, str) else None, request_source=body.source,
            models_used=[body.model], providers_used=[body.provider],
            provider_metadata={"cost_ingest": {"idempotency_key": body.idempotency_key, "payload_hash": body.payload_hash()}},
            created_at=at, updated_at=at,
        )
    )
    log = CostLog(
        session_id=session_id, model=body.model, input_tokens=body.input_tokens, output_tokens=body.output_tokens,
        cache_read_tokens=body.cache_read_tokens, cache_write_tokens=body.cache_write_tokens,
        cost_usd=body.cost_usd if body.billing_kind == "metered" else 0.0, billing_mode=body.billing_kind,
        api_equiv_usd=_api_equiv(body), cost_note=f"ingested from {body.source}"[:200], created_at=at,
    )
    db.add(log)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent retry of the same entry won the insert.
        await db.rollback()
        dup = await _existing(db, body, session_id)
        if dup is None:
            raise
        response.status_code = 200
        return dup
    http_request.state.session_id = session_id  # request_logs attribution
    logger.info("cost ingest: recorded session %s", session_id)
    return CostIngestResponse(status="created", session_id=session_id, cost_log_id=log.id,
                              billing_kind=log.billing_mode, cost_usd=float(log.cost_usd))

