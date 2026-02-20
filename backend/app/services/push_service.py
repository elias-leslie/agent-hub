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
    """
    if not is_configured():
        logger.debug("Web Push not configured (missing VAPID keys)")
        return 0

    subs = await get_subscriptions(db, user_email=user_email)
    if not subs:
        return 0

    vapid_claims = {"sub": settings.vapid_subject}
    data = json.dumps(payload)
    sent = 0

    dirty = False
    for sub in subs:
        subscription_info = {
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=data,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims=vapid_claims,
            )
            sent += 1
            dirty = True
            # Touch last_used_at
            sub.last_used_at = func.now()
        except WebPushException as e:
            if hasattr(e, "response") and e.response is not None and e.response.status_code == 410:
                logger.info("Push subscription expired, removing: %s", sub.endpoint[:50])
                await db.delete(sub)
                dirty = True
            else:
                logger.exception("Failed to send push to %s", sub.endpoint[:50])
        except Exception:
            logger.exception("Unexpected error sending push to %s", sub.endpoint[:50])

    if dirty:
        await db.commit()

    if sent > 0:
        logger.info("Push delivered to %d/%d subscriptions", sent, len(subs))

    return sent
