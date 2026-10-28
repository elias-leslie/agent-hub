"""Project permission model: registered project root, cost budgets and cost-ingest gate."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ProjectPermission(Base):
    """Registered project row: root path, cost budgets and the cost-ingest gate.

    Tool access comes from each agent's own tool list, and pausing autonomous
    runs is an Automations policy, so no tier or execution window lives here.
    """

    __tablename__ = "project_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    root_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    daily_cost_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # null = unlimited
    monthly_cost_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # null = unlimited
    budget_alert_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.8"
    )  # 0.0-1.0
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ProjectPermission project_id={self.project_id!r}>"
