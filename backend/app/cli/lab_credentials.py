"""Authorized local lab enrollment, refresh and trusted child delivery."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from app.storage.lab_credentials import (
    LabCredentialError,
    LabCredentialRequest,
    ResolvedLabCredential,
    decode_lab_json,
    enroll_lab_credential,
    lab_reference,
    list_lab_credential_refs,
    refresh_lab_credential,
    resolve_lab_credentials,
)

# Version 1 local wire limit, shared by input documents and the handoff bundle.
MAX_DOCUMENT_BYTES = 65536
HANDOFF_FD_ENV = "AGENT_HUB_LAB_CREDENTIAL_FD"


def _read_document(path: Path | None, *, protected: bool) -> object:
    """Read stdin or an opened file, checking the descriptor before reading."""
    fd = os.dup(0) if path is None else os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        regular = stat.S_ISREG(info.st_mode)
        if not regular and not (path is None and stat.S_ISFIFO(info.st_mode)):
            raise LabCredentialError("Lab input must be a regular file or piped stdin")
        if protected and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise LabCredentialError("Enrollment input must be owner-owned and private")
        data = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise LabCredentialError("Lab document exceeds the local wire limit")
    return decode_lab_json(data)


def _requests(document: object) -> list[LabCredentialRequest]:
    if not isinstance(document, list) or not document:
        raise LabCredentialError("Lab selection must be a nonempty list")
    result = []
    for item in document:
        if (not isinstance(item, dict) or set(item) != {"reference", "fields"}
                or not isinstance(item["reference"], str)
                or not isinstance(item["fields"], list)
                or any(not isinstance(name, str) for name in item["fields"])):
            raise LabCredentialError("Invalid lab credential selection")
        result.append(LabCredentialRequest(item["reference"], tuple(item["fields"])))
    return result


def _handoff(target: str, resolved: list[ResolvedLabCredential], command: list[str]) -> int:
    """Deliver JSON on an anonymous descriptor to one trusted executable."""
    if not command or not Path(command[0]).is_absolute():
        raise LabCredentialError("A trusted absolute child executable is required")
    payload = json.dumps({
        "schema_version": 1,
        "target": target,
        "credentials": [{"reference": item.reference, "values": item.values} for item in resolved],
    }).encode()
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise LabCredentialError("Lab handoff exceeds the local wire limit")
    reader, writer = socket.socketpair()
    try:
        # Queue the bounded bundle before launching. Insufficient socket capacity
        # fails closed instead of blocking before a reader exists. No listener,
        # pathname, writer thread or temporary secret file is involved.
        reader.shutdown(socket.SHUT_WR)
        writer.setblocking(False)
        writer.sendall(payload)
        writer.shutdown(socket.SHUT_WR)
        fd = reader.fileno()
        result = subprocess.run(
            command,
            env={"PATH": os.defpath, HANDOFF_FD_ENV: str(fd)},
            pass_fds=(fd,), close_fds=True, check=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return result.returncode if result.returncode >= 0 else 128 - result.returncode
    finally:
        reader.close()
        writer.close()


async def _database_action(action: str, target: str, **arguments: Any) -> Any:
    # Only the trusted owner operation loads Agent Hub's existing DB/key config.
    from app.db import async_session

    async with async_session() as db:
        if action == "enroll":
            return await enroll_lab_credential(db, **arguments)
        if action == "refresh":
            return await refresh_lab_credential(db, **arguments)
        if action == "refs":
            return await list_lab_credential_refs(db, target)
        if action == "run":
            return await resolve_lab_credentials(db, target, arguments["requests"])
    raise LabCredentialError("Unknown local lab credential operation")


def run_lab_operation(action: str, *, target: str, **arguments: Any) -> dict[str, Any]:
    """Synchronous local CLI boundary; all errors are sanitized by its caller.

    File reads and child waits stay outside the async database runtime. Resolved
    values leave the database session only as value-opaque snapshots.
    """
    if action in {"enroll", "refresh"}:
        reference = lab_reference(target, arguments["actor"])
        values = _read_document(arguments["input_file"], protected=True)
        if not isinstance(values, dict):
            raise LabCredentialError("Enrollment input must be a field object")
        expiry = arguments.get("expires_at")
        try:
            expires_at = datetime.fromisoformat(expiry) if expiry is not None else None
        except ValueError:
            raise LabCredentialError("Invalid lab credential expiry") from None
        options = {"kind": arguments["kind"]} if action == "enroll" else {}
        enrolled = asyncio.run(_database_action(
            action, target, reference=reference, values=values,
            expires_at=expires_at, **options,
        ))
        return {"reference": enrolled}
    if action == "refs":
        return {"references": asyncio.run(_database_action("refs", target))}
    if action == "run":
        requests = _requests(_read_document(arguments["request_file"], protected=False))
        command = arguments["command"]
        if not command or not Path(command[0]).is_absolute():
            raise LabCredentialError("A trusted absolute child executable is required")
        resolved = asyncio.run(_database_action("run", target, requests=requests))
        return {"exit_code": _handoff(target, resolved, command)}
    raise LabCredentialError("Unknown local lab credential operation")
