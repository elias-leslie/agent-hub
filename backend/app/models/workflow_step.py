"""Durable steps of a multi-model workflow run.

A run is a ``sessions`` row (session_type ``workflow``); each attempt at a step is a child
session. This table holds the step ledger the runner advances.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

WORKFLOW_STEP_STATUSES = (
    "pending",
    "running",
    "completed",
    "failed",
    "refused",
    "needs_owner",
    "skipped",
)


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    step_key: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    restarts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    current_attempt_session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    chosen_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    handoff: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    checkpoint_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("run_session_id", "step_key", name="uq_workflow_steps_run_key"),
        UniqueConstraint("run_session_id", "position", name="uq_workflow_steps_run_position"),
        CheckConstraint(
            "status IN ('pending','running','completed','failed','refused','needs_owner','skipped','cancelled')",
            name="ck_workflow_steps_status",
        ),
        Index("ix_workflow_steps_status_heartbeat", "status", "heartbeat_at"),
        Index("ix_workflow_steps_current_attempt", "current_attempt_session_id"),
    )
