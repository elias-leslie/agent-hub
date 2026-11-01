"""Context observability: what Agent Hub delivered, recorded when it was built."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ContextDelivery(Base):
    """One context delivery: who asked, the role it was for, and its blocks with source revision and tokens.

    delivery_id is the canonical delivery id (the same id the client writes into its contract file), so a
    transcript's delivered CLAUDE.md or Codex developer text binds to its row by payload_hash. Recorded at the real
    delivery sites (record=True); previews and dry runs never land here. source: api | host | cli | agent | workflow |
    file (imported from a delivery contract file, for history before recording began).
    """

    __tablename__ = "context_deliveries"

    delivery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    surface: Mapped[str] = mapped_column(String(100), nullable=False)
    profile: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    agent_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    work_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    coordinator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    consumer_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    host: Mapped[str | None] = mapped_column(String(100), nullable=True)
    est_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rendered_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    by_scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # [{block_id, kind, source_type, source_id, revision, scope, tokens}]
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_context_deliveries_generated_at", "generated_at"),
        Index("ix_context_deliveries_surface_generated", "surface", "generated_at"),
        Index("ix_context_deliveries_payload_hash", "payload_hash"),
    )


class ContextBudget(Base):
    """Warn level for a harness x role cell's median first-turn tokens; policy data the owner edits.

    One row per (harness or '*', role or '*'); role is a Cost-matrix cell (a launch-table job, 'blank',
    'subagent:<type>', 'unknown'). The most specific row wins: exact, then harness, then role, then ('*', '*').
    jump_pct is the one global step threshold and lives only on the ('*', '*') row.
    """

    __tablename__ = "context_budgets"

    harness: Mapped[str] = mapped_column(String(20), primary_key=True)
    role: Mapped[str] = mapped_column(String(80), primary_key=True)
    warn_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    jump_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("jump_pct IS NULL OR (harness = '*' AND role = '*')", name="ck_context_budgets_jump_global"),
        CheckConstraint("warn_tokens > 0", name="ck_context_budgets_warn_positive"),
    )


class ContextKnob(Base):
    """A config file of ours that changes what a harness loads (for example Tether's lane-tools.json).

    A step in a cell's first turn that comes with a config fingerprint change is named after the knob files that
    changed in git just before it. harness/role '*' match every harness or cell. repo_path is the git checkout
    holding file_path (relative to it).
    """

    __tablename__ = "context_knobs"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    harness: Mapped[str] = mapped_column(String(20), nullable=False, server_default="*")
    role: Mapped[str] = mapped_column(String(80), nullable=False, server_default="*")
    repo_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
