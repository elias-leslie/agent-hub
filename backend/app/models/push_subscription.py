"""Push subscription model for Web Push notifications."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PushSubscription(Base):
    """Browser push subscription for Web Push notifications.

    Stores the subscription info from PushManager.subscribe() so the server
    can send push notifications via VAPID.
    """

    __tablename__ = "push_subscriptions"

    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    p256dh_key: Mapped[str] = mapped_column(Text, nullable=False)
    auth_key: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL/NULL marks preserved legacy subscriptions, never a wildcard scope.
    application_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_push_subscriptions_application_owner", "application_id", "owner_id"),)
