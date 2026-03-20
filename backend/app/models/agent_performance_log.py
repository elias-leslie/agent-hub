"""Agent performance log — dimensional tracking for agentxmodelxtask_type performance."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AgentPerformanceLog(Base):
    """Tracks agent/model performance for persona-directed model management.

    Each row represents one performance observation filed by the persona,
    system automation, or human override. Provides dimensional queryability
    for agent x model x task_type x outcome analysis.
    """

    __tablename__ = "agent_performance_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Dimensions
    agent_slug: Mapped[str] = mapped_column(String(100), index=True)
    model_id: Mapped[str] = mapped_column(String(200), index=True)
    task_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Outcome
    outcome: Mapped[str] = mapped_column(String(20))  # success, partial, failure, timeout, fallback
    feedback_type: Mapped[str] = mapped_column(String(20))  # friction, improvement, idea, praise

    # Metrics
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_calls_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turns: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Content
    content: Mapped[str] = mapped_column(Text)  # Persona-authored or system-authored observation text

    # Provenance
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logged_by: Mapped[str] = mapped_column(String(20), server_default="persona")  # persona, system, human

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_agent_perf_agent_created", "agent_slug", "created_at"),
        Index("ix_agent_perf_model_created", "model_id", "created_at"),
        Index("ix_agent_perf_agent_model_type", "agent_slug", "model_id", "task_type"),
        Index("ix_agent_perf_feedback_type", "feedback_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<AgentPerformanceLog agent={self.agent_slug!r} model={self.model_id!r} "
            f"outcome={self.outcome!r} type={self.feedback_type!r}>"
        )
