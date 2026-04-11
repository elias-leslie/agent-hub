"""Persistent enable/disable controls for static workflow schedules."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class WorkflowScheduleControl(Base):
    """Per-schedule runtime toggle for Hatchet cron workflows."""

    __tablename__ = "workflow_schedule_controls"

    schedule_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    updated_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<WorkflowScheduleControl schedule_id={self.schedule_id!r} enabled={self.enabled!r}>"
