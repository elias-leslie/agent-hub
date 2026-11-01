"""The owner's after-the-fact decisions on agent context changes (keep, rework, refuse)."""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ContextChangeReview(Base):
    """One decision on one target's changes, through one revision.

    target_kind: memory (target_id = memory uuid) | prompt (prompt slug) | placement (``profile|project``
    placement layer). through_revision is the revision id the reviewer saw last (memory_revisions.id,
    prompt_revisions.id or context_records.id); result_revision is the revision a rework or refuse wrote.
    covered_until is the time of the later of the two: the target's non-owner changes after it are unreviewed.
    """

    __tablename__ = "context_change_reviews"

    id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4)
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(String(200), nullable=False)
    through_revision: Mapped[str] = mapped_column(String(36), nullable=False)
    result_revision: Mapped[str | None] = mapped_column(String(36), nullable=True)
    covered_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # keep | rework | refuse
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    by_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    by_session: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_context_change_reviews_target", "target_kind", "target_id", "created_at"),
        Index("ix_context_change_reviews_created_at", "created_at"),
    )
