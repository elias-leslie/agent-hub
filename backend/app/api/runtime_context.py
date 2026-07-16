"""Runtime context profile API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.api_key_auth import AuthenticatedKey, require_api_key
from app.services.runtime_context import (
    KNOWN_RUNTIME_PROFILES,
    CanonicalContextDeliveryRequest,
    CanonicalContextDeliveryResponse,
    RuntimeContextOverridePayload,
    RuntimeContextOverrideResponse,
    RuntimeContextPreviewResponse,
    RuntimeContextProfilePolicyResponse,
    RuntimeContextProfilePolicyUpdate,
    build_canonical_context_delivery,
    get_runtime_context_profile_policy,
    list_runtime_context_overrides,
    render_runtime_context,
    replace_runtime_context_overrides,
    upsert_runtime_context_profile_policy,
)

router = APIRouter(prefix="/runtime-context", tags=["runtime-context"])


class RuntimeContextProfileResponse(BaseModel):
    consumer_profile: str
    label: str


class RuntimeContextProfilesResponse(BaseModel):
    profiles: list[RuntimeContextProfileResponse]


class RuntimeContextOverrideListResponse(BaseModel):
    overrides: list[RuntimeContextOverrideResponse]


class RuntimeContextOverrideReplaceRequest(BaseModel):
    overrides: list[RuntimeContextOverridePayload] = Field(default_factory=list)


@router.post("/deliver", response_model=CanonicalContextDeliveryResponse)
async def deliver_runtime_context(
    request: CanonicalContextDeliveryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> CanonicalContextDeliveryResponse:
    """Return additive, versioned context for Agent Hub and external TUIs."""
    return await build_canonical_context_delivery(db, request)


@router.get("/profiles", response_model=RuntimeContextProfilesResponse)
async def list_runtime_context_profiles(
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> RuntimeContextProfilesResponse:
    return RuntimeContextProfilesResponse(
        profiles=[
            RuntimeContextProfileResponse(
                consumer_profile=profile,
                label=profile.replace("_", " ").title(),
            )
            for profile in KNOWN_RUNTIME_PROFILES
        ]
    )


@router.get("/{consumer_profile}/overrides", response_model=RuntimeContextOverrideListResponse)
async def get_runtime_context_overrides(
    consumer_profile: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    project_id: Annotated[str | None, Query(description="Optional project-specific override layer")] = None,
) -> RuntimeContextOverrideListResponse:
    overrides = await list_runtime_context_overrides(
        db,
        consumer_profile=consumer_profile,
        project_id=project_id,
    )
    return RuntimeContextOverrideListResponse(overrides=overrides)


@router.put("/{consumer_profile}/overrides", response_model=RuntimeContextOverrideListResponse)
async def put_runtime_context_overrides(
    consumer_profile: str,
    request: RuntimeContextOverrideReplaceRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    project_id: Annotated[str | None, Query(description="Optional project-specific override layer")] = None,
) -> RuntimeContextOverrideListResponse:
    overrides = await replace_runtime_context_overrides(
        db,
        consumer_profile=consumer_profile,
        project_id=project_id,
        overrides=request.overrides,
    )
    return RuntimeContextOverrideListResponse(overrides=overrides)


@router.get("/{consumer_profile}/policy", response_model=RuntimeContextProfilePolicyResponse)
async def get_runtime_context_policy(
    consumer_profile: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> RuntimeContextProfilePolicyResponse:
    return await get_runtime_context_profile_policy(
        db, consumer_profile=consumer_profile
    )


@router.put("/{consumer_profile}/policy", response_model=RuntimeContextProfilePolicyResponse)
async def put_runtime_context_policy(
    consumer_profile: str,
    payload: RuntimeContextProfilePolicyUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> RuntimeContextProfilePolicyResponse:
    return await upsert_runtime_context_profile_policy(
        db, consumer_profile=consumer_profile, payload=payload
    )


@router.get("/{consumer_profile}/preview", response_model=RuntimeContextPreviewResponse)
async def preview_runtime_context(
    consumer_profile: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    project_id: Annotated[str | None, Query(description="Optional project ID")] = None,
    query: Annotated[str, Query(description="Selection query")] = "startup context",
    task_type: Annotated[str | None, Query(description="Optional task type trigger")] = None,
    phase: Annotated[str | None, Query(description="Optional phase trigger")] = None,
    include_global: Annotated[bool, Query(description="Include global memory with project memory")] = True,
) -> RuntimeContextPreviewResponse:
    return await render_runtime_context(
        db,
        consumer_profile=consumer_profile,
        project_id=project_id,
        query=query,
        task_type=task_type,
        phase=phase,
        include_global=include_global,
    )
