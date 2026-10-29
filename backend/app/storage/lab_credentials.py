"""Scoped lab references in the existing encrypted credential store.

The caller must supply a trusted target scope. This module authenticates no caller,
exposes no endpoint and never falls back to host/provider sources.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Credential
from app.services.system_credentials import LAB_PROVIDER_PREFIX

_TARGET = r"[a-z0-9][a-z0-9._-]{0,79}"
_ACTOR = r"[a-z0-9][a-z0-9._-]{0,49}"
_REFERENCE = re.compile(rf"secret://lab/(?P<target>{_TARGET})/(?P<actor>{_ACTOR})")
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class LabCredentialError(ValueError):
    """A fixed diagnostic that never includes credential contents."""


def decode_lab_json(value: str | bytes) -> object:
    """Reject ambiguous JSON without including input in diagnostics."""
    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise LabCredentialError("Duplicate lab JSON key")
            result[key] = item
        return result

    try:
        return json.loads(value, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError):
        raise LabCredentialError("Invalid lab credential JSON") from None


def lab_reference(target: str, actor: str) -> str:
    reference = f"secret://lab/{target}/{actor}"
    _identity(reference)
    return reference


def _provider(target: str) -> str:
    if not isinstance(target, str) or not re.fullmatch(_TARGET, target):
        raise LabCredentialError("Invalid target scope")
    return f"{LAB_PROVIDER_PREFIX}{target}"


@dataclass(frozen=True)
class LabCredentialRequest:
    reference: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedLabCredential:
    reference: str
    values: dict[str, str] = field(repr=False)


def _identity(reference: str) -> tuple[str, str]:
    match = _REFERENCE.fullmatch(reference)
    if match is None:
        raise LabCredentialError("Invalid lab credential reference")
    return match["target"], match["actor"]


def _timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LabCredentialError("Credential timestamps must include a timezone")
    return value.astimezone(UTC)


def _validate_payload(
    payload: object, reference: str, now: datetime, *, allow_expired: bool = False,
) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "reference", "kind", "expires_at", "values",
    }:
        raise LabCredentialError("Invalid lab credential payload")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1 or payload["reference"] != reference:
        raise LabCredentialError("Lab credential identity mismatch")
    if payload["kind"] not in ("synthetic", "temporary", "account"):
        raise LabCredentialError("Unsupported lab credential kind")
    expiry = payload["expires_at"]
    if expiry is not None:
        try:
            expires_at = datetime.fromisoformat(expiry)
        except (TypeError, ValueError):
            raise LabCredentialError("Invalid lab credential expiry") from None
        if _timestamp(expires_at) <= now and not allow_expired:
            raise LabCredentialError("Lab credential expired")
    elif payload["kind"] == "temporary":
        raise LabCredentialError("Temporary lab credentials require an expiry")
    values = payload["values"]
    if not isinstance(values, dict) or not values:
        raise LabCredentialError("Invalid lab credential fields")
    validated: dict[str, str] = {}
    for key, value in values.items():
        if (not isinstance(key, str) or not _FIELD.fullmatch(key)
                or not isinstance(value, str) or not value):
            raise LabCredentialError("Invalid lab credential fields")
        validated[key] = value
    return validated


def prepare_lab_credential(
    reference: str,
    values: dict[str, str],
    *,
    kind: str,
    expires_at: datetime | None = None,
    now: datetime | None = None,
) -> Credential:
    """Prepare an encrypted ORM row without persisting it."""
    target, actor = _identity(reference)
    payload = {
        "schema_version": 1,
        "reference": reference,
        "kind": kind,
        "expires_at": _timestamp(expires_at).isoformat() if expires_at is not None else None,
        "values": values,
    }
    _validate_payload(payload, reference, _timestamp(now or datetime.now(UTC)))
    # Reuse Agent Hub's encryption/key custody; no second vault or key source.
    from app.storage.credentials import encrypt_value

    return Credential(
        provider=f"{LAB_PROVIDER_PREFIX}{target}",
        credential_type=actor,
        value_encrypted=encrypt_value(json.dumps(payload)),
    )


async def enroll_lab_credential(
    db: AsyncSession,
    reference: str,
    values: dict[str, str],
    *,
    kind: str,
    expires_at: datetime | None = None,
) -> str:
    """Insert once under a PostgreSQL writer lock; own the transaction.

    Enrollment never replaces a row. The lock covers all credential writers,
    since the existing table has no unique target/actor constraint.
    """
    target, actor = _identity(reference)
    async with db.begin():
        await db.execute(text("LOCK TABLE credentials IN SHARE ROW EXCLUSIVE MODE"))
        existing = await db.execute(select(Credential.id).where(
            Credential.provider == _provider(target), Credential.credential_type == actor,
        ))
        if existing.all():
            raise LabCredentialError("Lab credential reference already exists or is ambiguous")
        # Validate expiry after acquiring the lock, which may have waited.
        credential = prepare_lab_credential(reference, values, kind=kind, expires_at=expires_at)
        db.add(credential)
        await db.flush()
    return reference


async def refresh_lab_credential(
    db: AsyncSession,
    reference: str,
    values: dict[str, str],
    *,
    expires_at: datetime | None = None,
) -> str:
    """Replace one known synthetic or owner account bundle, including an expired one, in place.

    The trusted local operator supplies authority; neither a reference nor the
    kind label grants permission to change an account on a target.
    """
    target, actor = _identity(reference)
    async with db.begin():
        await db.execute(text("LOCK TABLE credentials IN SHARE ROW EXCLUSIVE MODE"))
        result = await db.execute(select(Credential).where(
            Credential.provider == _provider(target), Credential.credential_type == actor,
        ))
        rows = result.scalars().all()
        if (len(rows) != 1 or rows[0].provider != _provider(target)
                or rows[0].credential_type != actor):
            raise LabCredentialError("Lab credential unavailable or ambiguous")
        from app.storage.credentials import EncryptionError, decrypt_value

        try:
            payload = decode_lab_json(decrypt_value(rows[0].value_encrypted))
        except (EncryptionError, ValueError, UnicodeError):
            raise LabCredentialError("Lab credential could not be decoded") from None
        _validate_payload(payload, reference, datetime.now(UTC), allow_expired=True)
        if not isinstance(payload, dict) or payload["kind"] not in ("synthetic", "account"):
            raise LabCredentialError("Only known synthetic or account lab credentials can be refreshed")
        replacement = prepare_lab_credential(
            reference, values, kind=payload["kind"], expires_at=expires_at,
        )
        rows[0].value_encrypted = replacement.value_encrypted
        await db.flush()
    return reference


async def list_lab_credential_refs(db: AsyncSession, target: str) -> list[str]:
    """Read identity columns only; never fetch ciphertext or decrypt values."""
    provider = _provider(target)
    result = await db.execute(select(Credential.provider, Credential.credential_type).where(
        Credential.provider == provider,
    ).order_by(Credential.credential_type))
    refs: list[str] = []
    for row_provider, actor in result.all():
        if row_provider != provider:
            raise LabCredentialError("Lab credential outside target scope")
        reference = lab_reference(target, actor)
        if reference in refs:
            raise LabCredentialError("Lab credential lookup ambiguous or outside scope")
        refs.append(reference)
    return refs


async def resolve_lab_credentials(
    db: AsyncSession,
    target: str,
    requests: list[LabCredentialRequest],
    *,
    now: datetime | None = None,
) -> list[ResolvedLabCredential]:
    """Select only requested actors/fields within a trusted target scope.

    A future broker must derive target from the authenticated launch assignment,
    never from a sandbox's self-asserted request. Nothing is returned on failure.
    """
    _provider(target)
    actors: list[str] = []
    for request in requests:
        request_target, actor = _identity(request.reference)
        if request_target != target:
            raise LabCredentialError("Lab credential outside target scope")
        if actor in actors or not request.fields or len(set(request.fields)) != len(request.fields):
            raise LabCredentialError("Duplicate actor or invalid field selection")
        if any(not isinstance(name, str) or not _FIELD.fullmatch(name) for name in request.fields):
            raise LabCredentialError("Invalid lab credential field selection")
        actors.append(actor)
    if not actors:
        return []
    result = await db.execute(select(Credential).where(
        Credential.provider == f"{LAB_PROVIDER_PREFIX}{target}",
        Credential.credential_type.in_(actors),
    ))
    rows: dict[str, Credential] = {}
    for row in result.scalars().all():
        # Also reject an adapter returning rows beyond the exact requested scope.
        if (row.provider != f"{LAB_PROVIDER_PREFIX}{target}"
                or row.credential_type not in actors or row.credential_type in rows):
            raise LabCredentialError("Lab credential lookup ambiguous or outside scope")
        rows[row.credential_type] = row
    if set(rows) != set(actors):
        raise LabCredentialError("Lab credential unavailable")
    from app.storage.credentials import EncryptionError, decrypt_value

    resolved: list[ResolvedLabCredential] = []
    for request, actor in zip(requests, actors, strict=True):
        try:
            payload = decode_lab_json(decrypt_value(rows[actor].value_encrypted))
        except (EncryptionError, ValueError, UnicodeError):
            raise LabCredentialError("Lab credential could not be decoded") from None
        # The lookup and decryption may outlive a temporary credential.
        current_time = _timestamp(now if now is not None else datetime.now(UTC))
        values = _validate_payload(payload, request.reference, current_time)
        if not set(request.fields) <= values.keys():
            raise LabCredentialError("Requested lab credential field unavailable")
        resolved.append(ResolvedLabCredential(
            request.reference, {name: values[name] for name in request.fields},
        ))
    return resolved
