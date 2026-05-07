"""Project permission model for centralized automation access control."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

# Canonical project trust tiers.
#
# Legacy values are accepted at API/cache/DB boundaries only so old clients and
# unmigrated rows do not break during deploy.
VALID_PERMISSION_TIERS = ("off", "read", "full")
LEGACY_PERMISSION_TIER_ALIASES = {
    "write": "full",
    "yolo": "full",
}
ACCEPTED_PERMISSION_TIERS = VALID_PERMISSION_TIERS + tuple(LEGACY_PERMISSION_TIER_ALIASES)


def normalize_permission_tier(tier: str | None) -> str | None:
    """Return canonical permission tier, or None for missing/invalid input."""
    if tier is None:
        return None
    normalized = tier.strip().lower()
    if normalized in VALID_PERMISSION_TIERS:
        return normalized
    return LEGACY_PERMISSION_TIER_ALIASES.get(normalized)


class ProjectPermission(Base):
    """Per-project automation permission configuration.

    Controls which tools agents can use, whether auto-execution is enabled,
    and during what hours execution is allowed. This is the single source
    of truth for all automation access control across all projects.
    """

    __tablename__ = "project_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    permission_tier: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="read"
    )
    auto_exec_enabled: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"
    )
    execution_start_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    execution_end_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="24"
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
        return (
            f"<ProjectPermission project_id={self.project_id!r} "
            f"tier={self.permission_tier!r} auto_exec={self.auto_exec_enabled}>"
        )
