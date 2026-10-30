"""Remote hosts: owner management, and the host-token endpoints the host shim calls.

Owner routes (``/remote-hosts``, ``/remote-tools``) add, revoke and grant hosts and
edit the per-tool credential map. Host routes (``/host-credentials``) authenticate
with the host's own bearer token and are exempt from request logging; only the
fetch returns a value, only for a granted tool, never cached.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_identity import require_owner
from app.db import get_db
from app.storage.remote_hosts import (
    HostIdentity,
    HostSummary,
    RemoteHostExists,
    RemoteHostMissing,
    ToolCredentialState,
    ToolMapRow,
    ToolNotGranted,
    add_host,
    add_tool_row,
    authenticate_host,
    delete_tool_credential,
    delete_tool_row,
    list_hosts,
    resolve_host_credentials,
    revoke_host,
    set_tool_grant,
    store_tool_credential,
    tool_credential_states,
)

owner_router = APIRouter(dependencies=[Depends(require_owner)])
host_router = APIRouter(prefix="/host-credentials")
_NO_STORE = {"Cache-Control": "no-store"}


def _refused(exc: ValueError) -> HTTPException:
    """Storage messages are fixed text; nothing of the request is echoed."""
    if isinstance(exc, RemoteHostMissing):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RemoteHostExists):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ToolNotGranted):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


async def require_host(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> HostIdentity:
    """FastAPI dependency: the active remote host whose bearer token was presented."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    host = await authenticate_host(db, token.strip()) if scheme.lower() == "bearer" else None
    if host is None:
        raise HTTPException(status_code=401, detail="Unknown or revoked host token",
                            headers={"WWW-Authenticate": "Bearer"})
    return host


# Schemas -------------------------------------------------------------------


class HostItem(BaseModel):
    name: str
    granted_tools: list[str]
    created_at: datetime | None
    revoked_at: datetime | None
    last_seen_at: datetime | None

    @classmethod
    def of(cls, host: HostSummary) -> HostItem:
        return cls(**{**vars(host), "granted_tools": list(host.granted_tools)})


class HostList(BaseModel):
    hosts: list[HostItem]


class HostCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)


class HostToken(BaseModel):
    name: str
    token: str


class ToolRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_slug: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=50)
    command: str = Field(min_length=1, max_length=50)
    config_dir: str = Field(min_length=1, max_length=200)
    env_var: str | None = Field(default=None, max_length=100)
    auth_file: str | None = Field(default=None, max_length=200)
    rotates: bool
    description: str = Field(default="", max_length=1000)


class ToolState(ToolRow):
    stored: bool
    expires_at: datetime | None
    expired: bool
    updated_at: datetime | None
    undecodable: bool

    @classmethod
    def of(cls, state: ToolCredentialState) -> ToolState:
        return cls(**vars(state.row), stored=state.stored, expires_at=state.expires_at, expired=state.expired,
                   updated_at=state.updated_at, undecodable=state.undecodable)


class ToolStateList(BaseModel):
    credentials: list[ToolState]


class HostToolStates(ToolStateList):
    host: str
    granted_tools: list[str]


class CredentialValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: SecretStr = Field(min_length=1, max_length=32768)
    expires_at: datetime | None = None


class DeliveryItem(BaseModel):
    name: str
    config_dir: str
    env_var: str | None
    auth_file: str | None
    value: str


class DeliveryList(BaseModel):
    tool: str
    credentials: list[DeliveryItem]


# Owner: hosts --------------------------------------------------------------


@owner_router.get("/remote-hosts", response_model=HostList)
async def get_hosts(db: Annotated[AsyncSession, Depends(get_db)]) -> HostList:
    return HostList(hosts=[HostItem.of(host) for host in await list_hosts(db)])


@owner_router.post("/remote-hosts", response_model=HostToken, status_code=201)
async def post_host(body: HostCreate, db: Annotated[AsyncSession, Depends(get_db)], response: Response) -> HostToken:
    """Register a host; the token appears in this response only."""
    try:
        token = await add_host(db, body.name)
    except ValueError as exc:
        raise _refused(exc) from None
    response.headers.update(_NO_STORE)
    return HostToken(name=body.name, token=token)


@owner_router.delete("/remote-hosts/{name}", status_code=204)
async def delete_host(name: str, db: Annotated[AsyncSession, Depends(get_db)]) -> Response:
    """Revoke: the token stops working and every grant is dropped."""
    try:
        await revoke_host(db, name)
    except ValueError as exc:
        raise _refused(exc) from None
    return Response(status_code=204)


@owner_router.put("/remote-hosts/{name}/tools/{tool}", response_model=HostItem)
async def grant_tool(name: str, tool: str, db: Annotated[AsyncSession, Depends(get_db)]) -> HostItem:
    try:
        return HostItem.of(await set_tool_grant(db, name, tool, granted=True))
    except ValueError as exc:
        raise _refused(exc) from None


@owner_router.delete("/remote-hosts/{name}/tools/{tool}", response_model=HostItem)
async def deny_tool(name: str, tool: str, db: Annotated[AsyncSession, Depends(get_db)]) -> HostItem:
    try:
        return HostItem.of(await set_tool_grant(db, name, tool, granted=False))
    except ValueError as exc:
        raise _refused(exc) from None


# Owner: tool map and stored values -----------------------------------------


@owner_router.get("/remote-tools", response_model=ToolStateList)
async def get_tool_map(db: Annotated[AsyncSession, Depends(get_db)]) -> ToolStateList:
    """Every map row with whether a value is stored and its expiry; never values."""
    return ToolStateList(credentials=[ToolState.of(state) for state in await tool_credential_states(db)])


@owner_router.post("/remote-tools", response_model=ToolRow, status_code=201)
async def post_tool_row(body: ToolRow, db: Annotated[AsyncSession, Depends(get_db)]) -> ToolRow:
    try:
        await add_tool_row(db, ToolMapRow(**body.model_dump()))
    except ValueError as exc:
        raise _refused(exc) from None
    return body


@owner_router.delete("/remote-tools/{tool}/{name}", status_code=204)
async def delete_tool_map_row(tool: str, name: str, db: Annotated[AsyncSession, Depends(get_db)]) -> Response:
    try:
        await delete_tool_row(db, tool, name)
    except ValueError as exc:
        raise _refused(exc) from None
    return Response(status_code=204)


@owner_router.put("/remote-tools/{tool}/{name}/credential", response_model=ToolState)
async def put_tool_credential(
    tool: str, name: str, body: CredentialValue, db: Annotated[AsyncSession, Depends(get_db)],
) -> ToolState:
    try:
        state = await store_tool_credential(db, tool, name, body.value.get_secret_value(), expires_at=body.expires_at)
    except ValueError as exc:
        raise _refused(exc) from None
    return ToolState.of(state)


@owner_router.delete("/remote-tools/{tool}/{name}/credential", status_code=204)
async def delete_stored_credential(tool: str, name: str, db: Annotated[AsyncSession, Depends(get_db)]) -> Response:
    try:
        await delete_tool_credential(db, tool, name)
    except ValueError as exc:
        raise _refused(exc) from None
    return Response(status_code=204)


# Host token ----------------------------------------------------------------


@host_router.get("/tools", response_model=HostToolStates)
async def host_tool_states(
    host: Annotated[HostIdentity, Depends(require_host)], db: Annotated[AsyncSession, Depends(get_db)],
) -> HostToolStates:
    """The map and what Agent Hub holds, for this host's shim install and login status; never values."""
    states = [ToolState.of(state) for state in await tool_credential_states(db)]
    return HostToolStates(host=host.name, granted_tools=list(host.granted_tools), credentials=states)


@host_router.get("/{tool}", response_model=DeliveryList)
async def fetch_tool_credentials(
    tool: str, response: Response,
    host: Annotated[HostIdentity, Depends(require_host)], db: Annotated[AsyncSession, Depends(get_db)],
) -> DeliveryList:
    """The values a granted tool launches with. Never cached; this path is never request-logged."""
    try:
        deliveries = await resolve_host_credentials(db, host, tool)
    except ValueError as exc:
        raise _refused(exc) from None
    response.headers.update(_NO_STORE)
    return DeliveryList(tool=tool, credentials=[DeliveryItem(**vars(item)) for item in deliveries])


@host_router.put("/{tool}/{name}", response_model=ToolState)
async def push_tool_credential(
    tool: str, name: str, body: CredentialValue,
    host: Annotated[HostIdentity, Depends(require_host)], db: Annotated[AsyncSession, Depends(get_db)],
) -> ToolState:
    """Save a non-rotating value the owner just created on this host (e.g. `claude setup-token`)."""
    try:
        if tool not in host.granted_tools:
            raise ToolNotGranted("This host is not granted that tool")
        state = await store_tool_credential(db, tool, name, body.value.get_secret_value(), expires_at=body.expires_at)
    except ValueError as exc:
        raise _refused(exc) from None
    return ToolState.of(state)
