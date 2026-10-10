"""Durable session binding model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class SessionBinding(Base):
    """Resolve external work surfaces to canonical Agent Hub sessions."""

    __tablename__ = "session_bindings"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    surface: Mapped[str] = mapped_column(String(100), nullable=False, default="work_chats")
    pane_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    feedback_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    design_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    telegram_thread_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    telegram_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_client: Mapped[str | None] = mapped_column(String(100), nullable=True)
    work_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session = relationship("Session", lazy="raise")

    __table_args__ = (
        UniqueConstraint("surface", "pane_id", name="uq_session_bindings_surface_pane"),
        Index("ix_session_bindings_task", "project_id", "task_id"),
        Index("ix_session_bindings_telegram", "telegram_chat_id", "telegram_thread_id"),
    )

