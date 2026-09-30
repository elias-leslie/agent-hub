"""Source receipts are durable evidence; canonical command identities are independent."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class NativeObservationSource(Base):
    __tablename__ = "native_observation_sources"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    registration: Mapped[dict[str, Any]] = mapped_column(JSON)
    authenticity: Mapped[str] = mapped_column(String(32))
    committed_position: Mapped[int] = mapped_column(Integer, default=0)


class NativeCommandEntity(Base):
    __tablename__ = "native_command_entities"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    namespace: Mapped[str] = mapped_column(String(512))
    thread_id: Mapped[str] = mapped_column(String(512))
    turn_id: Mapped[str] = mapped_column(String(512))
    item_id: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32))
    command: Mapped[dict[str, Any]] = mapped_column(JSON)
    projection_event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    # This slice has no provider delivery receipt, so delivery remains unknown.
    observed_model: Mapped[str | None] = mapped_column(String(512), nullable=True)


class NativeObservationReceipt(Base):
    __tablename__ = "native_observation_receipts"
    source_id: Mapped[str] = mapped_column(String(64), ForeignKey("native_observation_sources.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    observation: Mapped[dict[str, Any]] = mapped_column(JSON)
    disposition: Mapped[str] = mapped_column(String(32))
    issue_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("native_command_entities.id"), nullable=True, index=True)


class NativeObservationIssue(Base):
    __tablename__ = "native_observation_issues"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), ForeignKey("native_observation_sources.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(100))
    observation: Mapped[dict[str, Any]] = mapped_column(JSON)
