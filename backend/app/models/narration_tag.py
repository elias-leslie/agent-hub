"""Narration tag model for agent progress observability."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class NarrationTag(Base):
    """Progress narration tags extracted from agent session messages.

    Agents emit [[P:type:content]] tags during execution. These are parsed
    from assistant_message events and stored for timeline display and analysis.
    """

    __tablename__ = "task_narration_tags"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    tag_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_narration_tags_task_created", "task_id", "created_at"),
        Index("ix_narration_tags_session", "session_id"),
        Index("ix_narration_tags_type", "tag_type"),
        UniqueConstraint(
            "task_id",
            "session_id",
            "tag_type",
            "content",
            name="uq_narration_tags_task_session_type_content",
        ),
    )

    def __repr__(self) -> str:
        return f"<NarrationTag id={self.id!r} task={self.task_id!r} type={self.tag_type!r}>"
