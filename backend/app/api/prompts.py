"""Prompt management API endpoints.

CRUD for prompts and prompt-to-agent assignments.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.prompt_schemas import (
    AgentPromptAssignRequest,
    AgentPromptListResponse,
    AgentPromptResponse,
    AgentPromptUpdateRequest,
    PromptCreateRequest,
    PromptListResponse,
    PromptResponse,
    PromptRestoreRequest,
    PromptRevisionListResponse,
    PromptRevisionResponse,
    PromptUpdateRequest,
    RolesResponse,
)
from app.db import get_db
from app.services.agent_service import get_agent_service
from app.services.api_key_auth import AuthenticatedKey, require_api_key
from app.services.compactness import CompactnessValidationError
from app.services.prompt_service import (
    assign_prompt,
    create_prompt,
    delete_prompt,
    get_agent_prompts,
    get_all_prompts,
    get_distinct_roles,
    get_prompt_by_slug,
    get_prompt_revision,
    list_prompt_revisions,
    remove_assignment,
    restore_prompt_revision,
    update_assignment,
    update_prompt,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompts", tags=["prompts"])


async def _invalidate_owned_agent_cache(prompt: object | None) -> None:
    from app.models.prompt import Prompt
    from app.services.owned_prompt_service import AGENT_SYSTEM_PROMPT_TYPE

    if not isinstance(prompt, Prompt):
        return
    owner_agent = prompt.__dict__.get("owner_agent")
    if prompt.prompt_type != AGENT_SYSTEM_PROMPT_TYPE or owner_agent is None:
        return

    service = get_agent_service()
    await service.invalidate_slug(owner_agent.slug)


def _prompt_to_response(p: object) -> PromptResponse:
    from app.models.prompt import Prompt

    assert isinstance(p, Prompt)
    owner_agent = p.__dict__.get("owner_agent")
    return PromptResponse(
        id=p.id,
        slug=p.slug,
        name=p.name,
        content=p.content,
        description=p.description,
        is_global=p.is_global,
        enabled=p.enabled,
        boot_eligible=bool(p.boot_eligible),
        exclude_agents=p.exclude_agents or [],
        owner_agent_slug=owner_agent.slug if owner_agent else None,
        prompt_type=p.prompt_type,
        deletion_locked=bool(p.deletion_locked),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _revision_to_response(revision: object) -> PromptRevisionResponse:
    from app.models.prompt import PromptRevision

    assert isinstance(revision, PromptRevision)
    return PromptRevisionResponse(
        id=revision.id,
        prompt_id=revision.prompt_id,
        prompt_slug=revision.prompt_slug,
        prompt_name=revision.prompt_name,
        action=revision.action,
        content=revision.content,
        description=revision.description,
        is_global=revision.is_global,
        enabled=revision.enabled,
        boot_eligible=bool(revision.boot_eligible),
        exclude_agents=revision.exclude_agents or [],
        owner_agent_id=revision.owner_agent_id,
        prompt_type=revision.prompt_type,
        deletion_locked=bool(revision.deletion_locked),
        content_hash=revision.content_hash,
        changed_by=revision.changed_by,
        change_reason=revision.change_reason,
        created_at=revision.created_at,
    )


@router.get("", response_model=PromptListResponse)
async def list_prompts(
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    is_global: bool | None = None,
) -> PromptListResponse:
    prompts = await get_all_prompts(db, is_global=is_global)
    return PromptListResponse(
        prompts=[_prompt_to_response(p) for p in prompts],
        total=len(prompts),
    )


@router.get("/roles", response_model=RolesResponse)
async def list_roles(
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> RolesResponse:
    roles = await get_distinct_roles(db)
    return RolesResponse(roles=roles)


@router.post("", response_model=PromptResponse, status_code=201)
async def create_prompt_endpoint(
    request: PromptCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> PromptResponse:
    existing = await get_prompt_by_slug(db, request.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Prompt '{request.slug}' already exists")

    try:
        prompt = await create_prompt(
            db,
            slug=request.slug,
            name=request.name,
            content=request.content,
            description=request.description,
            is_global=request.is_global,
            enabled=request.enabled,
            boot_eligible=request.boot_eligible,
            exclude_agents=request.exclude_agents,
            changed_by="api",
        )
    except CompactnessValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": "compactness_error", "errors": list(exc.errors)}) from exc
    return _prompt_to_response(prompt)


@router.get("/{slug}", response_model=PromptResponse)
async def get_prompt_endpoint(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> PromptResponse:
    prompt = await get_prompt_by_slug(db, slug)
    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt '{slug}' not found")
    return _prompt_to_response(prompt)


@router.put("/{slug}", response_model=PromptResponse)
async def update_prompt_endpoint(
    slug: str,
    request: PromptUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> PromptResponse:
    update_data = request.model_dump(exclude_unset=True)
    change_reason = update_data.pop("change_reason", None)
    try:
        updated = await update_prompt(
            db,
            slug,
            changed_by="api",
            change_reason=change_reason,
            **update_data,
        )
    except CompactnessValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": "compactness_error", "errors": list(exc.errors)}) from exc
    if not updated:
        raise HTTPException(status_code=404, detail=f"Prompt '{slug}' not found")
    await _invalidate_owned_agent_cache(updated)
    return _prompt_to_response(updated)


@router.get("/{slug}/revisions", response_model=PromptRevisionListResponse)
async def list_prompt_revisions_endpoint(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    limit: int = 20,
) -> PromptRevisionListResponse:
    revisions = await list_prompt_revisions(db, slug, limit=limit)
    return PromptRevisionListResponse(
        revisions=[_revision_to_response(revision) for revision in revisions],
        total=len(revisions),
    )


@router.post("/{slug}/revisions/{revision_id}/restore", response_model=PromptResponse)
async def restore_prompt_revision_endpoint(
    slug: str,
    revision_id: str,
    request: PromptRestoreRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> PromptResponse:
    try:
        revision = await get_prompt_revision(db, slug, revision_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not revision:
        raise HTTPException(status_code=404, detail="Prompt revision not found")

    try:
        restored = await restore_prompt_revision(
            db,
            slug,
            revision_id,
            changed_by="api",
            change_reason=request.change_reason,
        )
    except CompactnessValidationError as exc:
        raise HTTPException(status_code=422, detail={"error": "compactness_error", "errors": list(exc.errors)}) from exc
    if not restored:
        raise HTTPException(status_code=404, detail=f"Prompt '{slug}' not found")
    await _invalidate_owned_agent_cache(restored)
    return _prompt_to_response(restored)


@router.delete("/{slug}", status_code=204)
async def delete_prompt_endpoint(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> None:
    prompt = await get_prompt_by_slug(db, slug)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{slug}' not found")
    try:
        deleted = await delete_prompt(db, slug)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Prompt '{slug}' not found")
    await _invalidate_owned_agent_cache(prompt)


# --- Agent prompt assignment endpoints (nested under /prompts/agents) ---


@router.get("/agents/{agent_slug}/assignments", response_model=AgentPromptListResponse)
async def list_agent_prompts(
    agent_slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentPromptListResponse:
    service = get_agent_service()
    agent = await service.get_by_slug(db, agent_slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_slug}' not found")

    assignments = await get_agent_prompts(db, agent.id)
    return AgentPromptListResponse(
        assignments=[
            AgentPromptResponse(
                prompt=_prompt_to_response(ap.prompt),
                role=ap.role,
                priority=ap.priority,
            )
            for ap in assignments
        ]
    )


@router.post(
    "/agents/{agent_slug}/assignments",
    response_model=AgentPromptResponse,
    status_code=201,
)
async def assign_prompt_endpoint(
    agent_slug: str,
    request: AgentPromptAssignRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentPromptResponse:
    service = get_agent_service()
    agent = await service.get_by_slug(db, agent_slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_slug}' not found")

    prompt = await get_prompt_by_slug(db, request.prompt_slug)
    if not prompt:
        raise HTTPException(
            status_code=404, detail=f"Prompt '{request.prompt_slug}' not found"
        )

    assignment = await assign_prompt(
        db,
        agent_id=agent.id,
        prompt_id=prompt.id,
        role=request.role,
        priority=request.priority,
    )
    await db.refresh(assignment, ["prompt"])
    return AgentPromptResponse(
        prompt=_prompt_to_response(assignment.prompt),
        role=assignment.role,
        priority=assignment.priority,
    )


@router.put("/agents/{agent_slug}/assignments/{prompt_slug}")
async def update_assignment_endpoint(
    agent_slug: str,
    prompt_slug: str,
    request: AgentPromptUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> AgentPromptResponse:
    service = get_agent_service()
    agent = await service.get_by_slug(db, agent_slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_slug}' not found")

    prompt = await get_prompt_by_slug(db, prompt_slug)
    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_slug}' not found")

    updated = await update_assignment(
        db,
        agent.id,
        prompt.id,
        role=request.role,
        priority=request.priority,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Assignment not found")

    await db.refresh(updated, ["prompt"])
    return AgentPromptResponse(
        prompt=_prompt_to_response(updated.prompt),
        role=updated.role,
        priority=updated.priority,
    )


@router.delete("/agents/{agent_slug}/assignments/{prompt_slug}", status_code=204)
async def remove_assignment_endpoint(
    agent_slug: str,
    prompt_slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> None:
    service = get_agent_service()
    agent = await service.get_by_slug(db, agent_slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_slug}' not found")

    prompt = await get_prompt_by_slug(db, prompt_slug)
    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_slug}' not found")

    removed = await remove_assignment(db, agent.id, prompt.id)
    if not removed:
        raise HTTPException(status_code=404, detail="Assignment not found")
