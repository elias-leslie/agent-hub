"""Remote hosts, their tool grants, and the non-rotating tool credentials they fetch.

Host tokens are stored as SHA-256 hashes; the plaintext leaves only once, from
``add_host``. Served values live in the existing encrypted ``credentials`` table
(provider ``_host_tool_<tool>``, type ``<name>``) and come back only from
``resolve_host_credentials`` for a granted, non-revoked host. Rotating map rows
are never stored or served: those logins stay on the host that signed in.
Errors carry fixed text and never include a value or token.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Credential, RemoteHost, RemoteToolCredential
from app.services.system_credentials import HOST_TOOL_PROVIDER_PREFIX

_HOST = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")
_TOOL = re.compile(r"[a-z0-9][a-z0-9-]{0,49}")
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,49}")
_COMMAND = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,49}")
_ENV_VAR = re.compile(r"[A-Z_][A-Z0-9_]{0,99}")
TOKEN_PREFIX = "ahh_"
MAX_VALUE_CHARS = 32768


class RemoteHostError(ValueError):
    """A fixed diagnostic that never includes a token or credential value."""


class RemoteHostMissing(RemoteHostError):
    """No such host, map row or stored credential."""


class RemoteHostExists(RemoteHostError):
    """An active host or map row already has that name."""


class ToolNotGranted(RemoteHostError):
    """The host may not fetch this tool's credentials."""


@dataclass(frozen=True)
class HostIdentity:
    """Snapshot of an authenticated host, safe to use after the session closes."""

    name: str
    granted_tools: tuple[str, ...]


@dataclass(frozen=True)
class HostSummary:
    name: str
    granted_tools: tuple[str, ...]
    created_at: datetime | None
    revoked_at: datetime | None
    last_seen_at: datetime | None


@dataclass(frozen=True)
class ToolMapRow:
    tool_slug: str
    name: str
    command: str
    config_dir: str
    env_var: str | None
    auth_file: str | None
    rotates: bool
    description: str


@dataclass(frozen=True)
class ToolCredentialState:
    """A map row plus what Agent Hub holds for it; never the value."""

    row: ToolMapRow
    stored: bool
    expires_at: datetime | None
    expired: bool
    updated_at: datetime | None
    undecodable: bool


@dataclass(frozen=True)
class Delivery:
    """One credential for the host shim: set env_var, or write auth_file under config_dir."""

    name: str
    config_dir: str
    env_var: str | None
    auth_file: str | None
    value: str = field(repr=False)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _check(pattern: re.Pattern[str], value: object, message: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise RemoteHostError(message)
    return value


def _snapshot(row: RemoteToolCredential) -> ToolMapRow:
    return ToolMapRow(
        tool_slug=row.tool_slug, name=row.name, command=row.command, config_dir=row.config_dir,
        env_var=row.env_var, auth_file=row.auth_file, rotates=row.rotates, description=row.description,
    )


def _summary(host: RemoteHost) -> HostSummary:
    return HostSummary(
        name=host.name, granted_tools=tuple(host.granted_tools or ()), created_at=host.created_at,
        revoked_at=host.revoked_at, last_seen_at=host.last_seen_at,
    )


# Hosts ---------------------------------------------------------------------


async def _host(db: AsyncSession, name: str) -> RemoteHost:
    _check(_HOST, name, "Invalid host name")
    host = (await db.execute(select(RemoteHost).where(RemoteHost.name == name))).scalar_one_or_none()
    if host is None:
        raise RemoteHostMissing("No such host")
    return host


async def add_host(db: AsyncSession, name: str) -> str:
    """Register a host (or re-admit a revoked one) and return its new token, shown once.

    A re-admitted host starts with no grants.
    """
    _check(_HOST, name, "Invalid host name")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    existing = (await db.execute(select(RemoteHost).where(RemoteHost.name == name))).scalar_one_or_none()
    if existing is not None and existing.revoked_at is None:
        raise RemoteHostExists("Host already registered; revoke it first to issue a new token")
    if existing is None:
        db.add(RemoteHost(name=name, token_hash=hash_token(token), granted_tools=[]))
    else:
        existing.token_hash = hash_token(token)
        existing.granted_tools = []
        existing.revoked_at = None
        existing.last_seen_at = None
    await db.commit()
    return token


async def revoke_host(db: AsyncSession, name: str) -> None:
    """Stop every future fetch: drop grants and replace the token hash with one nothing matches."""
    host = await _host(db, name)
    host.revoked_at = datetime.now(UTC)
    host.granted_tools = []
    host.token_hash = hash_token(secrets.token_urlsafe(32))
    await db.commit()


async def set_tool_grant(db: AsyncSession, name: str, tool: str, *, granted: bool) -> HostSummary:
    host = await _host(db, name)
    _check(_TOOL, tool, "Invalid tool slug")
    if host.revoked_at is not None:
        raise RemoteHostError("Host is revoked")
    if granted and not (await db.execute(
        select(RemoteToolCredential.id).where(RemoteToolCredential.tool_slug == tool).limit(1)
    )).first():
        raise RemoteHostMissing("No credential map rows for that tool")
    tools = [item for item in host.granted_tools or [] if item != tool]
    host.granted_tools = sorted([*tools, tool]) if granted else tools
    await db.commit()
    return _summary(host)


async def list_hosts(db: AsyncSession) -> list[HostSummary]:
    rows = (await db.execute(select(RemoteHost).order_by(RemoteHost.name))).scalars().all()
    return [_summary(row) for row in rows]


async def authenticate_host(db: AsyncSession, token: str | None) -> HostIdentity | None:
    """The active host whose token this is, or None. Records when it was last seen."""
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    host = (await db.execute(
        select(RemoteHost).where(RemoteHost.token_hash == hash_token(token))
    )).scalar_one_or_none()
    if host is None or host.revoked_at is not None:
        return None
    host.last_seen_at = datetime.now(UTC)
    identity = HostIdentity(name=host.name, granted_tools=tuple(host.granted_tools or ()))
    await db.commit()
    return identity


# Tool map ------------------------------------------------------------------


async def list_tool_map(db: AsyncSession, tool: str | None = None) -> list[ToolMapRow]:
    query = select(RemoteToolCredential).order_by(RemoteToolCredential.tool_slug, RemoteToolCredential.name)
    if tool is not None:
        query = query.where(RemoteToolCredential.tool_slug == tool)
    return [_snapshot(row) for row in (await db.execute(query)).scalars().all()]


def _relative_file(path: str) -> str:
    parts = path.split("/")
    if not path or path.startswith("/") or any(part in ("", ".", "..") for part in parts) or len(path) > 200:
        raise RemoteHostError("Auth file must be a plain relative path under the config dir")
    return path


def _config_dir(path: str) -> str:
    rest = path.removeprefix("~/")
    if rest == path or len(path) > 200:
        raise RemoteHostError("Config dir must start with ~/")
    _relative_file(rest)
    return path


async def add_tool_row(db: AsyncSession, row: ToolMapRow) -> ToolMapRow:
    _check(_TOOL, row.tool_slug, "Invalid tool slug")
    _check(_NAME, row.name, "Invalid credential name")
    _check(_COMMAND, row.command, "Invalid command name")
    _config_dir(row.config_dir)
    if (row.env_var is None) == (row.auth_file is None):
        raise RemoteHostError("Give exactly one of env_var or auth_file")
    if row.env_var is not None:
        _check(_ENV_VAR, row.env_var, "Invalid env var name")
    if row.auth_file is not None:
        _relative_file(row.auth_file)
    existing = (await db.execute(select(RemoteToolCredential.id).where(
        RemoteToolCredential.tool_slug == row.tool_slug, RemoteToolCredential.name == row.name,
    ))).first()
    if existing:
        raise RemoteHostExists("That tool already has a credential with this name")
    db.add(RemoteToolCredential(**vars(row)))
    await db.commit()
    return row


async def delete_tool_row(db: AsyncSession, tool: str, name: str) -> None:
    """Remove a map row and any value stored for it."""
    row = await _map_row(db, tool, name)
    async with _credential_lock(db):
        for stored in await _stored_rows(db, tool, name):
            await db.delete(stored)
        await db.delete(row)
    await db.commit()


# Stored values -------------------------------------------------------------


async def _map_row(db: AsyncSession, tool: str, name: str) -> RemoteToolCredential:
    _check(_TOOL, tool, "Invalid tool slug")
    _check(_NAME, name, "Invalid credential name")
    row = (await db.execute(select(RemoteToolCredential).where(
        RemoteToolCredential.tool_slug == tool, RemoteToolCredential.name == name,
    ))).scalar_one_or_none()
    if row is None:
        raise RemoteHostMissing("No such tool credential")
    return row


async def _stored_rows(db: AsyncSession, tool: str, name: str) -> list[Credential]:
    return list((await db.execute(select(Credential).where(
        Credential.provider == f"{HOST_TOOL_PROVIDER_PREFIX}{tool}", Credential.credential_type == name,
    ))).scalars().all())


class _credential_lock:
    """The writer lock every credentials-table writer takes (see app.storage.lab_credentials)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def __aenter__(self) -> None:
        await self.db.execute(text("LOCK TABLE credentials IN SHARE ROW EXCLUSIVE MODE"))

    async def __aexit__(self, *exc: object) -> None:
        return None


def _timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RemoteHostError("Expiry must include a timezone")
    return value.astimezone(UTC)


async def store_tool_credential(
    db: AsyncSession, tool: str, name: str, value: str, *, expires_at: datetime | None = None,
) -> ToolCredentialState:
    """Save (or replace) the value for a non-rotating map row, encrypted."""
    from app.storage.credentials import encrypt_value

    row = await _map_row(db, tool, name)
    if row.rotates:
        raise RemoteHostError("This login rotates; sign in on the host instead")
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_VALUE_CHARS:
        raise RemoteHostError("Credential value must be nonempty text")
    expiry = _timestamp(expires_at) if expires_at is not None else None
    if expiry is not None and expiry <= datetime.now(UTC):
        raise RemoteHostError("Expiry is in the past")
    payload = json.dumps({"schema_version": 1, "value": value.strip(),
                          "expires_at": expiry.isoformat() if expiry else None})
    async with _credential_lock(db):
        existing = await _stored_rows(db, tool, name)
        for extra in existing[1:]:
            await db.delete(extra)
        if existing:
            existing[0].value_encrypted = encrypt_value(payload)
            existing[0].updated_at = datetime.now(UTC)
        else:
            db.add(Credential(provider=f"{HOST_TOOL_PROVIDER_PREFIX}{tool}", credential_type=name,
                              value_encrypted=encrypt_value(payload)))
    await db.commit()
    return ToolCredentialState(row=_snapshot(row), stored=True, expires_at=expiry, expired=False,
                               updated_at=datetime.now(UTC), undecodable=False)


async def delete_tool_credential(db: AsyncSession, tool: str, name: str) -> None:
    await _map_row(db, tool, name)
    async with _credential_lock(db):
        rows = await _stored_rows(db, tool, name)
        if not rows:
            raise RemoteHostMissing("Nothing stored for that tool credential")
        for row in rows:
            await db.delete(row)
    await db.commit()


def _decode(row: Credential) -> tuple[str, datetime | None]:
    from app.storage.credentials import EncryptionError, decrypt_value

    try:
        payload = json.loads(decrypt_value(row.value_encrypted))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError
        value, expiry = payload["value"], payload["expires_at"]
        if not isinstance(value, str) or not value:
            raise ValueError
        return value, _timestamp(datetime.fromisoformat(expiry)) if expiry else None
    except (EncryptionError, KeyError, TypeError, ValueError, UnicodeError):
        raise RemoteHostError("Stored tool credential could not be decoded") from None


async def tool_credential_states(db: AsyncSession, tool: str | None = None) -> list[ToolCredentialState]:
    """Every map row with whether a value is stored, its expiry and age; values never leave."""
    now = datetime.now(UTC)
    states: list[ToolCredentialState] = []
    for row in await list_tool_map(db, tool):
        stored = [] if row.rotates else await _stored_rows(db, row.tool_slug, row.name)
        expiry: datetime | None = None
        undecodable = False
        if stored:
            try:
                _, expiry = _decode(stored[0])
            except RemoteHostError:
                undecodable = True
        states.append(ToolCredentialState(
            row=row, stored=bool(stored), expires_at=expiry, expired=expiry is not None and expiry <= now,
            updated_at=stored[0].updated_at if stored else None, undecodable=undecodable,
        ))
    return states


async def resolve_host_credentials(db: AsyncSession, host: HostIdentity, tool: str) -> list[Delivery]:
    """The current, unexpired values for a tool this host is granted. Fails rather than return none."""
    _check(_TOOL, tool, "Invalid tool slug")
    if tool not in host.granted_tools:
        raise ToolNotGranted("This host is not granted that tool")
    now = datetime.now(UTC)
    deliveries: list[Delivery] = []
    for row in await list_tool_map(db, tool):
        if row.rotates:
            continue
        stored = await _stored_rows(db, tool, row.name)
        if len(stored) != 1:
            continue
        value, expiry = _decode(stored[0])
        if expiry is not None and expiry <= now:
            continue
        deliveries.append(Delivery(name=row.name, config_dir=row.config_dir, env_var=row.env_var,
                                   auth_file=row.auth_file, value=value))
    if not deliveries:
        raise RemoteHostMissing("No current credential is stored for that tool")
    return deliveries
