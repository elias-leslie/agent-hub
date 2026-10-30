"""Canonical context delivery for remote agent hosts.

A host has no Agent Hub database, so its `agent-hub-context deliver` posts here
with the host's bearer token (see integrations/context-delivery/bin/
agent-hub-context-remote). The internal-only `/runtime-context/deliver` route is
unreachable from a host; this one serves the same contract to any active host
and records which host asked.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.remote_hosts import require_host
from app.db import get_db
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    CanonicalContextDeliveryResponse,
    build_canonical_context_delivery,
)
from app.storage.remote_hosts import HostIdentity

router = APIRouter(prefix="/host-context", tags=["remote-hosts"])


@router.post("/deliver", response_model=CanonicalContextDeliveryResponse)
async def deliver_host_context(
    request: CanonicalContextDeliveryRequest,
    host: Annotated[HostIdentity, Depends(require_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CanonicalContextDeliveryResponse:
    request = request.model_copy(
        update={"client_metadata": {**request.client_metadata, "remote_host": host.name}}
    )
    return await build_canonical_context_delivery(db, request)
