"""Web Push notification service.

Shared, application-scoped Web Push transport. It owns no application inbox.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, cast

from pywebpush import WebPushException, webpush
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.push_subscription import PushSubscription
from app.services.push_scope import PushScope

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """Check if VAPID keys are configured."""
    return bool(settings.vapid_public_key and settings.vapid_private_key)


async def save_subscription(
    db: AsyncSession,
    endpoint: str,
    p256dh: str,
    auth: str,
    *,
    scope: PushScope,
    user_email: str | None = None,
) -> dict[str, Any]:
    """Upsert within a principal's application; never steal another scope.

    Endpoint uniqueness is global: distinct application service workers create
    distinct endpoints. A legacy endpoint can be explicitly re-registered only
    by presenting its existing keys, rather than guessing its old ownership.
    """
    sub_id = str(uuid.uuid4())[:8]

    stmt = (
        pg_insert(PushSubscription)
        .values(
            id=sub_id,
            endpoint=endpoint,
            p256dh_key=p256dh,
            auth_key=auth,
            application_id=scope.application_id,
            owner_id=scope.owner_id,
            user_email=user_email,
        )
        .on_conflict_do_update(
            index_elements=["endpoint"],
            set_={
                "p256dh_key": p256dh,
                "auth_key": auth,
                "application_id": scope.application_id,
                "owner_id": scope.owner_id,
                "user_email": user_email,
            },
            where=or_(
                and_(PushSubscription.application_id == scope.application_id,
                     PushSubscription.owner_id == scope.owner_id),
                and_(PushSubscription.application_id.is_(None),
                     PushSubscription.owner_id.is_(None),
                     PushSubscription.p256dh_key == p256dh,
                     PushSubscription.auth_key == auth),
            ),
        )
        .returning(PushSubscription.id)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        await db.rollback()
        raise ValueError("Subscription belongs to a different application or owner.")
    await db.commit()
    return {"id": row, "application_id": scope.application_id, "owner_id": scope.owner_id}


def subscription_scope(scope: PushScope):
    """NULL legacy scope is reachable only through the named compatibility path."""
    owned = and_(PushSubscription.application_id == scope.application_id,
                 PushSubscription.owner_id == scope.owner_id)
    if scope.include_legacy and scope.application_id == "summitflow":
        return or_(owned, and_(PushSubscription.application_id.is_(None),
                              PushSubscription.owner_id.is_(None)))
    return owned


async def delete_subscription(db: AsyncSession, endpoint: str, *, scope: PushScope) -> bool:
    """Remove only a subscription visible to the same service principal."""
    stmt = delete(PushSubscription).where(PushSubscription.endpoint == endpoint, subscription_scope(scope))
    result = await db.execute(stmt)
    await db.commit()
    return cast(CursorResult[Any], result).rowcount > 0


async def get_subscriptions(
    db: AsyncSession, *, scope: PushScope, user_email: str | None = None
) -> list[PushSubscription]:
    """Get only subscriptions for the bound application and service owner."""
    stmt = select(PushSubscription).where(subscription_scope(scope)).order_by(PushSubscription.created_at.desc())
    if user_email:
        stmt = stmt.where(PushSubscription.user_email == user_email)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def send_push(
    db: AsyncSession,
    payload: dict[str, Any],
    user_email: str | None = None,
    *,
    scope: PushScope | None = None,
) -> int:
    """Send only within the bound application/owner and return provider acceptances.

    Existing direct Agent Hub callers are confined to its dashboard principal.
    A provider acceptance is not evidence of notification display or human receipt.
    """
    if not is_configured():
        logger.debug("Web Push not configured (missing VAPID keys)")
        return 0

    scope = scope or PushScope("agent-hub", settings.agent_hub_dashboard_client_id)
    subs = await get_subscriptions(db, scope=scope, user_email=user_email)
    if not subs:
        return 0

    # Copy subscription identity before transport and concurrent updates.
    sub_infos = [
        {
            "id": sub.id,
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
            "application_id": sub.application_id,
            "owner_id": sub.owner_id,
        }
        for sub in subs
    ]

    vapid_claims = {"sub": settings.vapid_subject}
    data = json.dumps(payload)
    sent = 0
    expired: list[dict[str, Any]] = []
    delivered: list[dict[str, Any]] = []

    # Send from the captured identity; never log endpoint keys or provider errors.
    for info in sub_infos:
        try:
            webpush(
                subscription_info={
                    "endpoint": info["endpoint"],
                    "keys": info["keys"],
                },
                data=data,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims=vapid_claims,
            )
            sent += 1
            delivered.append(info)
        except WebPushException as e:
            if hasattr(e, "response") and e.response is not None and e.response.status_code == 410:
                logger.info("Push subscription expired: %s", info["id"])
                expired.append(info)
            else:
                logger.warning("Push delivery failed for subscription %s", info["id"])
        except Exception as exc:
            logger.warning("Push delivery failed for subscription %s (%s)", info["id"], type(exc).__name__)

    # Reconcile DB updates after network I/O.
    # Fence cleanup against a concurrent key rotation or explicit re-registration.
    for info in expired:
        await db.execute(delete(PushSubscription).where(_sent_subscription(info)))
    for info in delivered:
        await db.execute(update(PushSubscription).where(_sent_subscription(info)).values(last_used_at=func.now()))
    if expired or delivered:
        await db.commit()

    if sent > 0:
        logger.info("Push delivered to %d/%d subscriptions", sent, len(sub_infos))

    return sent


def _sent_subscription(info: dict[str, Any]):
    return and_(
        PushSubscription.id == info["id"],
        PushSubscription.application_id == info["application_id"],
        PushSubscription.owner_id == info["owner_id"],
        PushSubscription.p256dh_key == info["keys"]["p256dh"],
        PushSubscription.auth_key == info["keys"]["auth"],
    )
