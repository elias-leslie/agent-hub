"""Source receipts are durable evidence; canonical command identities are independent."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class NativeObservationSource(Base):
    __tablename__ = "native_observation_sources"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
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
    raw_pruned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload_hash: Mapped[str] = mapped_column(String(64))
    observation: Mapped[dict[str, Any]] = mapped_column(JSON)
    normalized: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
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


class NativeProtocolProfile(Base):
    __tablename__ = "native_protocol_profiles"
    provider_version: Mapped[str] = mapped_column(String(256), primary_key=True)
    schema_fingerprint: Mapped[str] = mapped_column(String(64))
    reference_profile_version: Mapped[str] = mapped_column(String(256))
    canary_sha256: Mapped[str] = mapped_column(String(64))
    canary_receipt: Mapped[dict[str, Any]] = mapped_column(JSON)
    qualified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NativeProjectionState(Base):
    __tablename__ = "native_projection_states"
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), default="shadow")
    acceptance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    next_sequence: Mapped[int] = mapped_column(Integer, default=1_000_000_000)


class NativeUserIdentity(Base):
    __tablename__ = "native_user_identities"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    namespace: Mapped[str] = mapped_column(String(512))
    thread_id: Mapped[str] = mapped_column(String(512))
    turn_id: Mapped[str] = mapped_column(String(512))
    client_id: Mapped[str] = mapped_column(String(512))
    durable_item_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    live_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    aliases: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    projection_event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
