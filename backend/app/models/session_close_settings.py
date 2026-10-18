"""Session close settings: when Agent Hub treats a quiet session as dead and closes it."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SessionCloseSettings(Base):
    """Singleton row (id=1); defaults match the formerly hardcoded thresholds."""

    __tablename__ = "session_close_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_session_close_settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    dead_candidate_after_minutes: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    reapable_after_minutes: Mapped[int] = mapped_column(Integer, default=360, server_default="360")
    zero_event_close_after_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    transcript_sync_close_after_minutes: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    completion_close_after_minutes: Mapped[int] = mapped_column(Integer, default=240, server_default="240")
    any_session_close_after_minutes: Mapped[int] = mapped_column(Integer, default=1440, server_default="1440")
    codex_close_inactive_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    codex_scan_hours: Mapped[int] = mapped_column(Integer, default=24, server_default="24")
    updated_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
