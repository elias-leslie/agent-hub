"""Canonical automation definitions, policies, profiles, and execution receipts."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AutomationDefinition(Base):
    __tablename__ = "automation_definitions"

    workflow_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_project_id: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dispatch_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    dispatch_target: Mapped[str] = mapped_column(String(300), nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(200))
    config_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    policy_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    default_schedule: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    default_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    manual_when_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual_advances_cursor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    overlap_strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AutomationProjectPolicy(Base):
    __tablename__ = "automation_project_policies"

    project_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sync_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_by: Mapped[str | None] = mapped_column(String(160))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AutomationProfile(Base):
    __tablename__ = "automation_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(160))
    workflow_key: Mapped[str] = mapped_column(String(160), nullable=False)
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    schedule_value: Mapped[str] = mapped_column(String(160), nullable=False)
    schedule_timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    clock_owner: Mapped[str] = mapped_column(String(20), nullable=False, default="legacy")
    owner_gate_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_ref: Mapped[str | None] = mapped_column(String(200), unique=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_runs: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    imported_unreviewed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_automation_profiles_due", "clock_owner", "enabled", "next_run_at"),
        Index("ix_automation_profiles_project", "project_id", "subject_id"),
    )


class AutomationProfileRevision(Base):
    __tablename__ = "automation_profile_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("automation_profiles.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("profile_id", "revision"),)


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("automation_profiles.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(100), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(160), nullable=False)
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    occurrence_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    gate_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    owner_run_id: Mapped[str | None] = mapped_column(String(200))
    owner_receipt: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_automation_runs_profile_created", "profile_id", "created_at"),)
