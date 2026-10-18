"""Subscription accounting API.

GET  /analytics/costs/accounting           cash, credits, utilization and API-equivalent value (kept separate)
GET  /analytics/subscriptions/plans        plan history
POST /analytics/subscriptions/plans        start a new plan period (closes the provider's open period)
GET  /analytics/subscriptions/credit-lots  credit lots
POST /analytics/subscriptions/credit-lots  record a grant or purchase
PATCH /analytics/subscriptions/credit-lots/{lot_id}  classify or correct a lot
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import CreditLot, SubscriptionPlan
from app.services.subscription_accounting import collector
from app.services.subscription_accounting.summary import build_summary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/costs/accounting")
async def get_cost_accounting(
    db: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    collect: Annotated[
        bool, Query(description="Also read new Codex/Claude Code log lines now (the usage timer does this every minute)")
    ] = False,
) -> dict[str, Any]:
    """Cash, credits, subscription headroom and API-equivalent value as separate blocks."""
    collected: dict[str, Any] = {"skipped": True}
    if collect:
        try:
            collected = await collector.collect(db)
        except Exception:
            logger.exception("subscription usage collection failed")
            await db.rollback()
            collected = {"error": "collection failed"}
    summary = await build_summary(db, days=days)
    summary["collector"] = collected
    return summary


class PlanIn(BaseModel):
    provider: str = Field(..., max_length=32)
    plan: str = Field(..., max_length=64)
    monthly_usd: float | None = Field(None, ge=0, description="null = price not verified")
    price_verified: bool = False
    effective_from: datetime
    evidence: str | None = None


def _plan_out(p: SubscriptionPlan) -> dict[str, Any]:
    return {
        "id": p.id, "provider": p.provider, "plan": p.plan, "monthly_usd": p.monthly_usd,
        "price_verified": p.price_verified, "effective_from": p.effective_from.isoformat(),
        "effective_to": p.effective_to.isoformat() if p.effective_to else None, "evidence": p.evidence,
    }


@router.get("/subscriptions/plans")
async def list_plans(db: Annotated[AsyncSession, Depends(get_db)]) -> list[dict[str, Any]]:
    rows = await db.execute(select(SubscriptionPlan).order_by(SubscriptionPlan.provider, SubscriptionPlan.effective_from))
    return [_plan_out(p) for p in rows.scalars()]


@router.post("/subscriptions/plans", status_code=201)
async def start_plan(body: PlanIn, db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, Any]:
    """A plan change starts a new row; the provider's open row ends where the new one begins."""
    if body.effective_from.tzinfo is None:
        raise HTTPException(422, "effective_from needs a timezone")
    later = await db.scalar(
        select(SubscriptionPlan.id).where(
            SubscriptionPlan.provider == body.provider, SubscriptionPlan.effective_from >= body.effective_from
        )
    )
    if later is not None:
        raise HTTPException(409, "A plan period already starts at or after effective_from")
    await db.execute(
        update(SubscriptionPlan)
        .where(SubscriptionPlan.provider == body.provider, SubscriptionPlan.effective_to.is_(None))
        .values(effective_to=body.effective_from)
    )
    plan = SubscriptionPlan(**body.model_dump())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return _plan_out(plan)


class CreditLotIn(BaseModel):
    provider: str = Field("codex", max_length=32)
    source: Literal["grant", "purchase", "unclassified"]
    credits: float = Field(..., gt=0)
    granted_at: datetime
    expires_at: datetime | None = None
    value_usd_per_credit: float | None = Field(None, ge=0, description="Reference value; grants are $0 cash")
    paid_usd: float | None = Field(None, ge=0, description="Cash paid (purchases)")
    evidence: str | None = None


class CreditLotPatch(BaseModel):
    source: Literal["grant", "purchase", "unclassified"] | None = None
    expires_at: datetime | None = None
    value_usd_per_credit: float | None = Field(None, ge=0)
    paid_usd: float | None = Field(None, ge=0)
    evidence: str | None = None


def _lot_out(lot: CreditLot) -> dict[str, Any]:
    return {
        "id": lot.id, "provider": lot.provider, "source": lot.source, "credits": lot.credits,
        "granted_at": lot.granted_at.isoformat(), "expires_at": lot.expires_at.isoformat() if lot.expires_at else None,
        "value_usd_per_credit": lot.value_usd_per_credit, "paid_usd": lot.paid_usd, "evidence": lot.evidence,
    }


@router.get("/subscriptions/credit-lots")
async def list_credit_lots(db: Annotated[AsyncSession, Depends(get_db)]) -> list[dict[str, Any]]:
    return [_lot_out(lot) for lot in (await db.execute(select(CreditLot).order_by(CreditLot.granted_at))).scalars()]


@router.post("/subscriptions/credit-lots", status_code=201)
async def add_credit_lot(body: CreditLotIn, db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, Any]:
    if body.source == "purchase" and body.paid_usd is None:
        raise HTTPException(422, "A purchase needs paid_usd")
    lot = CreditLot(**body.model_dump())
    db.add(lot)
    await db.commit()
    await db.refresh(lot)
    return _lot_out(lot)


@router.patch("/subscriptions/credit-lots/{lot_id}")
async def patch_credit_lot(
    lot_id: int, body: CreditLotPatch, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, Any]:
    lot = await db.get(CreditLot, lot_id)
    if lot is None:
        raise HTTPException(404, "Credit lot not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(lot, key, value)
    if lot.source == "purchase" and lot.paid_usd is None:
        raise HTTPException(422, "A purchase needs paid_usd")
    await db.commit()
    await db.refresh(lot)
    return _lot_out(lot)
