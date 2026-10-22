"""Explicit session-lifetime work roles; no inference from mutable runtime roles."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func

from app.models import Session

WORK_ROLES: dict[str, str] = json.loads(Path(__file__).with_suffix(".json").read_text())


class WorkRoleDeclaration(BaseModel):
    id: str
    source: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("id")
    @classmethod
    def registered_role(cls, value: str) -> str:
        if value not in WORK_ROLES:
            raise ValueError("Unknown work role ID")
        return value

    @field_validator("source", "display_name")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Work role provenance and display name cannot be blank")
        return value


class SessionWorkRole(WorkRoleDeclaration):
    label: str
    declared_at: datetime


class WorkRoleConflict(ValueError):
    code = "session_work_role_immutable"


def merge_work_role(existing: Any, incoming: Any) -> dict | None:
    """Retain the first declaration and its provenance, even on same-ID retries."""
    if incoming is None:
        return existing
    declaration = WorkRoleDeclaration.model_validate(incoming)
    if existing is not None:
        if not isinstance(existing, dict) or existing.get("id") != declaration.id:
            raise WorkRoleConflict("Session work role is fixed; declare a different role in a new session.")
        return existing
    return declaration.model_dump(exclude_none=True) | {"declared_at": datetime.now(UTC).isoformat()}


def session_work_role(session: Any) -> dict | None:
    metadata = session.provider_metadata if isinstance(getattr(session, "provider_metadata", None), dict) else {}
    value = metadata.get("work_role")
    if not isinstance(value, dict) or value.get("id") not in WORK_ROLES:
        return None
    if not value.get("source") or not value.get("declared_at"):
        return None
    return value | {"label": WORK_ROLES[value["id"]]}


def role_predicate(role_id: str):
    if role_id != "unknown" and role_id not in WORK_ROLES:
        raise ValueError("Unknown work role filter")
    raw = Session.provider_metadata["work_role"]
    known = raw["id"].as_string().in_(list(WORK_ROLES)) & raw["source"].as_string().is_not(None) & raw["declared_at"].as_string().is_not(None)
    return ~func.coalesce(known, False) if role_id == "unknown" else known & (raw["id"].as_string() == role_id)


def work_role_options() -> list[dict[str, str]]:
    return [{"id": key, "label": label} for key, label in WORK_ROLES.items()] + [{"id": "unknown", "label": "Unknown"}]
