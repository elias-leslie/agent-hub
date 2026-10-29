"""Owner-only management of lab credentials (agent logins): list, add, replace, edit, remove.

Metadata and the login URL are the only things read back. Values arrive in request
bodies, go straight to the encrypted store and appear in no response, log or error.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_identity import require_owner
from app.db import get_db
from app.storage.lab_credentials import (
    LabCredentialExists,
    LabCredentialMissing,
    delete_lab_credential,
    enroll_lab_credential,
    lab_reference,
    list_lab_credentials,
    refresh_lab_credential,
    update_lab_credential,
)

router = APIRouter(prefix="/lab-credentials", dependencies=[Depends(require_owner)])

_TEXT = Field(min_length=1, max_length=1000)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class AccountLogin(BaseModel):
    """A real login lent to agents, in the field names `st browser login` reads."""

    model_config = ConfigDict(extra="forbid")

    username: str = _TEXT
    password: SecretStr = Field(min_length=1, max_length=1000)
    login_url: str = _TEXT
    totp_secret: SecretStr | None = Field(default=None, max_length=1000)


class AccountCreate(AccountLogin):
    target: str = Field(min_length=1, max_length=80)
    actor: str = Field(default="default", min_length=1, max_length=50)


class LoginReplace(BaseModel):
    """Either the account fields or a complete `values` map for a synthetic bundle."""

    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None, min_length=1, max_length=1000)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=1000)
    login_url: str | None = Field(default=None, min_length=1, max_length=1000)
    totp_secret: SecretStr | None = Field(default=None, max_length=1000)
    values: dict[str, SecretStr] | None = None
    expires_at: datetime | None = None


class LoginPatch(BaseModel):
    """Merge: set these fields, drop those, keep the rest. Omit expires_at to keep it, null clears it."""

    model_config = ConfigDict(extra="forbid")

    set: dict[str, SecretStr] = Field(default_factory=dict)
    remove: list[str] = Field(default_factory=list, max_length=50)
    expires_at: datetime | None = None


class LabCredentialItem(BaseModel):
    reference: str
    target: str
    actor: str
    kind: str | None
    expires_at: datetime | None
    expired: bool
    fields: list[str]
    login_url: str | None
    created_at: datetime | None
    updated_at: datetime | None
    undecodable: bool


class LabCredentialList(BaseModel):
    credentials: list[LabCredentialItem]
    total: int


class LabCredentialRef(BaseModel):
    reference: str


def normalize_totp(text: str) -> str:
    """Base32 secret from a bare secret or otpauth:// URI; refuses non-default settings."""
    text = text.strip()
    if text.lower().startswith("otpauth://"):
        parts = urlsplit(text)
        query = {key.lower(): values[0] for key, values in parse_qs(parts.query).items() if values}
        if parts.netloc.lower() != "totp" or (
            query.get("algorithm", "SHA1").upper(), query.get("digits", "6"), query.get("period", "30"),
        ) != ("SHA1", "6", "30"):
            raise ValueError("The authenticator must be time-based with 6 digits, 30 seconds and SHA1")
        text = query.get("secret", "")
    secret = re.sub(r"[\s-]", "", text).upper().rstrip("=")
    try:
        if not re.fullmatch(r"[A-Z2-7]+", secret):
            raise ValueError
        base64.b32decode(secret + "=" * (-len(secret) % 8))
    except ValueError:
        raise ValueError("The authenticator secret is not base32 or an otpauth:// URI") from None
    return secret


def _login_url(value: str) -> str:
    parts = urlsplit(value.strip())
    host = parts.hostname or ""
    if not host or (parts.scheme != "https" and not (parts.scheme == "http" and host in _LOCAL_HOSTS)):
        raise ValueError("The login page must be an https URL")
    return value.strip()


def _account_values(body: AccountLogin) -> dict[str, str]:
    values = {
        "username": body.username.strip(),
        "password": body.password.get_secret_value(),
        "login_url": _login_url(body.login_url),
    }
    if not values["username"]:
        raise ValueError("A username is needed")
    if body.totp_secret is not None and body.totp_secret.get_secret_value().strip():
        values["totp_secret"] = normalize_totp(body.totp_secret.get_secret_value())
    return values


def _patched_values(given: dict[str, SecretStr]) -> dict[str, str]:
    """Normalise the account fields a patch touches; other fields pass as given."""
    values = {name: item.get_secret_value() for name, item in given.items()}
    if "username" in values:
        values["username"] = values["username"].strip()
    if "login_url" in values:
        values["login_url"] = _login_url(values["login_url"])
    if "totp_secret" in values:
        values["totp_secret"] = normalize_totp(values["totp_secret"])
    return values


def _refused(exc: ValueError) -> HTTPException:
    """Storage and validation messages are fixed text; nothing of the request is echoed."""
    if isinstance(exc, LabCredentialMissing):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, LabCredentialExists):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("", response_model=LabCredentialList)
async def list_logins(db: Annotated[AsyncSession, Depends(get_db)]) -> LabCredentialList:
    """Every lab row: metadata, field names and login URL only."""
    items = [
        LabCredentialItem(**{**vars(row), "fields": list(row.fields)})
        for row in await list_lab_credentials(db)
    ]
    return LabCredentialList(credentials=items, total=len(items))


@router.post("", response_model=LabCredentialRef, status_code=201)
async def add_account(
    body: AccountCreate, db: Annotated[AsyncSession, Depends(get_db)],
) -> LabCredentialRef:
    """Enroll a real login as kind `account`."""
    try:
        reference = lab_reference(body.target, body.actor)
        values = _account_values(body)
        await enroll_lab_credential(db, reference, values, kind="account")
    except ValueError as exc:
        raise _refused(exc) from None
    return LabCredentialRef(reference=reference)


@router.put("/{target}/{actor}", response_model=LabCredentialRef)
async def replace_login(
    target: str, actor: str, body: LoginReplace, db: Annotated[AsyncSession, Depends(get_db)],
) -> LabCredentialRef:
    """Replace a whole synthetic or account bundle; the kind is kept."""
    try:
        reference = lab_reference(target, actor)
        account = (body.username, body.password, body.login_url)
        if body.values is not None:
            if any(item is not None for item in account) or body.totp_secret is not None:
                raise ValueError("Send either the login fields or a values map")
            values = {key: item.get_secret_value() for key, item in body.values.items()}
        elif all(item is not None for item in account):
            values = _account_values(AccountLogin(
                username=body.username, password=body.password,
                login_url=body.login_url, totp_secret=body.totp_secret,
            ))
        else:
            raise ValueError("Replacing needs a username, password and login URL, or a values map")
        await refresh_lab_credential(db, reference, values, expires_at=body.expires_at)
    except ValueError as exc:
        raise _refused(exc) from None
    return LabCredentialRef(reference=reference)


@router.patch("/{target}/{actor}", response_model=LabCredentialRef)
async def edit_login(
    target: str, actor: str, body: LoginPatch, db: Annotated[AsyncSession, Depends(get_db)],
) -> LabCredentialRef:
    """Change some fields of a synthetic or account bundle without resending the rest."""
    try:
        reference = lab_reference(target, actor)
        expiry = {"expires_at": body.expires_at} if "expires_at" in body.model_fields_set else {}
        await update_lab_credential(
            db, reference, set_values=_patched_values(body.set), remove=body.remove, **expiry,
        )
    except ValueError as exc:
        raise _refused(exc) from None
    return LabCredentialRef(reference=reference)


@router.delete("/{target}/{actor}", status_code=204)
async def remove_login(
    target: str, actor: str, db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Delete one row, decodable or not."""
    try:
        await delete_lab_credential(db, lab_reference(target, actor))
    except ValueError as exc:
        raise _refused(exc) from None
    return Response(status_code=204)
