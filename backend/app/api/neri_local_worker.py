"""Neri local-worker API with a server-enforced passive request contract."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access_control_helpers import require_project_access
from app.api.neri_local_worker_schemas import (
    NeriLocalBenchmarkRequest,
    NeriLocalBenchmarkResponse,
    NeriLocalWorkerExecution,
    NeriLocalWorkerRequest,
    NeriLocalWorkerStatus,
)
from app.db import get_db
from app.services.api_key_auth import AuthenticatedKey, require_api_key
from app.services.neri_local_worker import (
    NeriLocalWorkerError,
    execute_neri_local_worker,
    get_neri_local_worker_status,
)
from app.services.neri_local_worker_benchmark import run_neri_local_benchmark

router = APIRouter(prefix="/neri/local-worker", tags=["neri-local-worker"])
_PROJECT_ID = "security-research"


@router.get("/status", response_model=NeriLocalWorkerStatus)
async def status(
    http_request: Request,
    _auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> NeriLocalWorkerStatus:
    """Report the exact candidate runtime identity and loopback health."""
    require_project_access(http_request, _PROJECT_ID)
    try:
        return await get_neri_local_worker_status()
    except NeriLocalWorkerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/evaluate", response_model=NeriLocalWorkerExecution)
async def evaluate(
    request: NeriLocalWorkerRequest,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> NeriLocalWorkerExecution:
    """Run one fresh local-only passive analysis with no generic completion inputs."""
    require_project_access(http_request, _PROJECT_ID)
    try:
        return await execute_neri_local_worker(request, db)
    except NeriLocalWorkerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/benchmarks", response_model=NeriLocalBenchmarkResponse)
async def benchmark(
    request: NeriLocalBenchmarkRequest,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> NeriLocalBenchmarkResponse:
    """Run a bounded development or locked harness comparison sequentially."""
    require_project_access(http_request, _PROJECT_ID)
    try:
        return await run_neri_local_benchmark(request, db)
    except (NeriLocalWorkerError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = ["router"]
