"""Local owner operations on remote hosts and the tool credential map (st agents hosts).

A new host token is written once to a private file the caller names, never printed,
so it stays out of agent transcripts. Stored credential values never come back here.
"""

from __future__ import annotations

import asyncio
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from app.storage.remote_hosts import (
    RemoteHostError,
    ToolMapRow,
    add_host,
    add_tool_row,
    delete_tool_row,
    list_hosts,
    revoke_host,
    set_tool_grant,
    store_tool_credential,
    tool_credential_states,
)

MAX_VALUE_BYTES = 32768


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _host(host: Any) -> dict[str, Any]:
    return {"name": host.name, "granted_tools": list(host.granted_tools), "created_at": _iso(host.created_at),
            "revoked_at": _iso(host.revoked_at), "last_seen_at": _iso(host.last_seen_at)}


def _write_private(path: Path, token: str) -> None:
    """Create the token file 0600; never overwrite an existing one."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")


def _read_value(path: Path | None) -> str:
    """A private regular file, or piped stdin; never a terminal or argv."""
    fd = os.dup(0) if path is None else os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) and not (path is None and stat.S_ISFIFO(info.st_mode)):
            raise RemoteHostError("Input must be a private regular file or piped stdin")
        if path is not None and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise RemoteHostError("Input file must be yours and private (chmod 600)")
        data = stream.read(MAX_VALUE_BYTES + 1)
    if len(data) > MAX_VALUE_BYTES:
        raise RemoteHostError("Credential value is too large")
    try:
        return data.decode("utf-8")
    except UnicodeError:
        raise RemoteHostError("Credential value must be UTF-8 text") from None


async def _database_action(action: str, arguments: dict[str, Any]) -> Any:
    from app.db import async_session

    async with async_session() as db:
        if action == "list":
            return {"hosts": [_host(host) for host in await list_hosts(db)]}
        if action == "add":
            return await add_host(db, arguments["name"])
        if action == "revoke":
            await revoke_host(db, arguments["name"])
            return {"revoked": arguments["name"]}
        if action in {"grant", "deny"}:
            host = await set_tool_grant(db, arguments["name"], arguments["tool"], granted=action == "grant")
            return _host(host)
        if action == "tools":
            return {"credentials": [
                {**vars(state.row), "stored": state.stored, "expires_at": _iso(state.expires_at),
                 "expired": state.expired, "updated_at": _iso(state.updated_at), "undecodable": state.undecodable}
                for state in await tool_credential_states(db)
            ]}
        if action == "tool-add":
            return vars(await add_tool_row(db, ToolMapRow(**arguments)))
        if action == "credential-set":
            state = await store_tool_credential(db, arguments["tool_slug"], arguments["name"], arguments["value"],
                                                expires_at=arguments["expires_at"])
            return {"tool": state.row.tool_slug, "name": state.row.name, "stored": True,
                    "expires_at": _iso(state.expires_at)}
        if action == "tool-remove":
            await delete_tool_row(db, arguments["tool_slug"], arguments["name"])
            return {"removed": f"{arguments['tool_slug']}/{arguments['name']}"}
    raise RemoteHostError("Unknown remote host operation")


def run_remote_host_operation(action: str, **arguments: Any) -> dict[str, Any]:
    """Synchronous CLI boundary; the caller prints only fixed errors."""
    if action == "add":
        token_out = Path(arguments.pop("token_out"))
        if token_out.exists() or token_out.is_symlink():
            raise RemoteHostError("Token file already exists")
        token = asyncio.run(_database_action("add", arguments))
        _write_private(token_out, token)
        return {"name": arguments["name"], "token_file": str(token_out)}
    if action == "credential-set":
        input_file = arguments.pop("input_file")
        expiry = arguments.pop("expires_at")
        try:
            arguments["expires_at"] = datetime.fromisoformat(expiry) if expiry else None
        except ValueError:
            raise RemoteHostError("Invalid expiry") from None
        arguments["value"] = _read_value(None if input_file == "-" else Path(input_file))
    return asyncio.run(_database_action(action, arguments))
