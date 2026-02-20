"""Web Push notification service.

Shared push delivery for all projects. Manages subscriptions and sends
notifications via the Web Push protocol with VAPID authentication.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, cast

from pywebpush import WebPushException, webpush
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.push_subscription import PushSubscription

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """Check if VAPID keys are configured."""
    return bool(settings.vapid_public_key and settings.vapid_private_key)


async def save_subscription(
    db: AsyncSession,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_email: str | None = None,
) -> dict[str, Any]:
    """Save or update a push subscription (upsert by endpoint)."""
    sub_id = str(uuid.uuid4())[:8]

    stmt = (
        pg_insert(PushSubscription)
        .values(
            id=sub_id,
            endpoint=endpoint,
            p256dh_key=p256dh,
            auth_key=auth,
            user_email=user_email,
        )
        .on_conflict_do_update(
            index_elements=["endpoint"],
            set_={
                "p256dh_key": p256dh,
                "auth_key": auth,
                "user_email": user_email,
            },
        )
        .returning(PushSubscription.id)
    )
    result = await db.execute(stmt)
    await db.commit()

    row = result.scalar_one_or_none()
    return {"id": row or sub_id, "endpoint": endpoint}


async def delete_subscription(db: AsyncSession, endpoint: str) -> bool:
    """Remove a push subscription by endpoint."""
    stmt = delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
    result = await db.execute(stmt)
    await db.commit()
    return cast(CursorResult[Any], result).rowcount > 0


async def get_subscriptions(
    db: AsyncSession, user_email: str | None = None
) -> list[PushSubscription]:
    """Get all subscriptions, optionally filtered by user email."""
    stmt = select(PushSubscription).order_by(PushSubscription.created_at.desc())
    if user_email:
        stmt = stmt.where(PushSubscription.user_email == user_email)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def send_push(
    db: AsyncSession,
    payload: dict[str, Any],
    user_email: str | None = None,
) -> int:
    """Send push notification to all (or user-specific) subscriptions.

    Returns the number of successful deliveries. Never raises.
    Loads subscriptions first, releases the DB connection, then sends
    pushes (network I/O) without holding a connection.
    """
    if not is_configured():
        logger.debug("Web Push not configured (missing VAPID keys)")
        return 0

    subs = await get_subscriptions(db, user_email=user_email)
    if not subs:
        return 0

    # Snapshot subscription data before releasing DB state
    sub_infos = [
        {
            "id": sub.id,
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
        }
        for sub in subs
    ]

    vapid_claims = {"sub": settings.vapid_subject}
    data = json.dumps(payload)
    sent = 0
    expired_endpoints: list[str] = []
    delivered_ids: list[str] = []

    # Send pushes without holding DB session active
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
            delivered_ids.append(info["id"])
        except WebPushException as e:
            if hasattr(e, "response") and e.response is not None and e.response.status_code == 410:
                logger.info("Push subscription expired, removing: %s", info["endpoint"][:50])
                expired_endpoints.append(info["endpoint"])
            else:
                logger.exception("Failed to send push to %s", info["endpoint"][:50])
        except Exception:
            logger.exception("Unexpected error sending push to %s", info["endpoint"][:50])

    # Batch DB updates after all network I/O is done
    if expired_endpoints:
        stmt = delete(PushSubscription).where(
            PushSubscription.endpoint.in_(expired_endpoints)
        )
        await db.execute(stmt)

    if delivered_ids:
        from sqlalchemy import update

        stmt = update(PushSubscription).where(
            PushSubscription.id.in_(delivered_ids)
        ).values(last_used_at=func.now())
        await db.execute(stmt)

    if expired_endpoints or delivered_ids:
        await db.commit()

    if sent > 0:
        logger.info("Push delivered to %d/%d subscriptions", sent, len(sub_infos))

    return sent
