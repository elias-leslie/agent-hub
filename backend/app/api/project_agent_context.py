"""Read-only summary of the startup context an agent receives in one project.

Projects the canonical delivery (the same selection agents get at session
start) into metadata only: no block content leaves this endpoint, and memories
above the ``normal`` sensitivity tier are withheld from the listing (counted,
not named). It lives outside ``/api/runtime-context`` so first-party clients
such as SummitFlow can read it; editing stays in Agent Hub's own UI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.project_roots import get_registered_project_roots
from app.db import get_db
from app.services.api_key_auth import AuthenticatedKey, require_api_key
from app.services.runtime_context import (
    CanonicalContextBlock,
    CanonicalContextDeliveryRequest,
    CanonicalContextDeliveryResponse,
    build_canonical_context_delivery,
)
from app.services.secret_redaction import redact_secrets

router = APIRouter(prefix="/projects", tags=["project-agent-context"])

# Mirrors the Claude Code launcher's startup delivery
# (integrations/context-delivery/claude/launcher).
DEFAULT_SURFACE = "claude_code"
DEFAULT_CAPABILITIES = ("bash",)
DEFAULT_PHASE = "startup"
RUNTIME_CONTEXT_PATH = "/runtime-context"
_LISTABLE_SENSITIVITY = {None, "normal"}

AgentContextKind = Literal["prompt", "memory", "project_index", "continuity", "tool_capabilities", "computed"]
AgentContextGroup = Literal["project", "global"]


class AgentContextItem(BaseModel):
    order: int
    kind: AgentContextKind
    group: AgentContextGroup
    source_id: str
    title: str
    authority: str
    tier: str
    required: bool
    disclosure: str
    reason: str
    char_count: int
    estimated_tokens: int
    edit_path: str | None = None
    facts: list[str] = Field(default_factory=list)


class AgentContextWithheld(BaseModel):
    count: int = 0
    estimated_tokens: int = 0


class AgentContextTotals(BaseModel):
    items: int
    project_items: int
    global_items: int
    project_tokens: int
    global_tokens: int
    item_tokens: int
    delivered_tokens: int
    delivered_chars: int


class AgentContextFailure(BaseModel):
    error_type: str
    message: str


class ProjectAgentContextResponse(BaseModel):
    project_id: str
    consumer_profile: str
    consumer_surface: str
    status: Literal["ok", "failed"]
    generated_at: datetime
    items: list[AgentContextItem] = Field(default_factory=list)
    withheld: AgentContextWithheld = Field(default_factory=AgentContextWithheld)
    totals: AgentContextTotals
    manage_path: str = RUNTIME_CONTEXT_PATH
    failure: AgentContextFailure | None = None


def _kind(block: CanonicalContextBlock) -> AgentContextKind:
    if block.provenance.source_type == "prompt":
        return "prompt"
    if block.provenance.source_type == "memory":
        return "memory"
    if block.kind in {"project_index", "continuity", "tool_capabilities"}:
        return block.kind  # type: ignore[return-value]
    return "computed"


def _group(block: CanonicalContextBlock, kind: AgentContextKind, project_id: str) -> AgentContextGroup:
    if kind in {"project_index", "continuity"}:
        return "project"
    if kind in {"tool_capabilities", "computed"}:
        return "global"
    provenance = block.provenance
    targets = {part.strip() for part in (provenance.scope_id or "").split(",") if part.strip()}
    return "project" if provenance.scope == "project" and project_id in targets else "global"


def _edit_path(kind: AgentContextKind, group: AgentContextGroup, source_id: str) -> str | None:
    if kind == "prompt":
        return f"/prompts/{quote(source_id, safe='')}"
    if kind == "memory":
        # The memory page filters by scope; it has no per-memory deep link yet.
        return f"/memory?scope={group}"
    return None


def _reason(block: CanonicalContextBlock) -> str:
    provenance = block.provenance
    if provenance.origin == "override":
        return "pinned in runtime context"
    reason = provenance.reason or ""
    if reason.startswith("tier:"):
        return f"{reason.removeprefix('tier:')} tier"
    return {
        "canonical_project_index": "generated from the project's .index.yaml",
        "canonical_continuity": "recent session continuity for this project",
        "canonical_tool_capabilities": "tools visible to this project",
    }.get(reason, reason)


def _index_facts(content: str) -> list[str]:
    body = content.removeprefix("<project-index>").removesuffix("</project-index>")
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError:
        return []
    return [str(key) for key in data] if isinstance(data, dict) else []


def summarize_delivery(
    delivery: CanonicalContextDeliveryResponse,
    *,
    project_id: str,
) -> ProjectAgentContextResponse:
    """Reduce a canonical delivery to listable, content-free metadata."""
    items: list[AgentContextItem] = []
    withheld = AgentContextWithheld()
    for block in delivery.blocks:
        if block.provenance.sensitivity_tier not in _LISTABLE_SENSITIVITY:
            withheld.count += 1
            withheld.estimated_tokens += block.estimated_tokens
            continue
        kind = _kind(block)
        group = _group(block, kind, project_id)
        items.append(
            AgentContextItem(
                order=block.order,
                kind=kind,
                group=group,
                source_id=block.provenance.source_id,
                title=redact_secrets(block.title)[0],
                authority=block.authority,
                tier=block.kind,
                required=block.required,
                disclosure=block.provenance.disclosure,
                reason=_reason(block),
                char_count=len(block.content),
                estimated_tokens=block.estimated_tokens,
                edit_path=_edit_path(kind, group, block.provenance.source_id),
                facts=_index_facts(block.content) if kind == "project_index" else [],
            )
        )
    project_items = [item for item in items if item.group == "project"]
    global_items = [item for item in items if item.group == "global"]
    totals = AgentContextTotals(
        items=len(items),
        project_items=len(project_items),
        global_items=len(global_items),
        project_tokens=sum(item.estimated_tokens for item in project_items),
        global_tokens=sum(item.estimated_tokens for item in global_items),
        item_tokens=sum(item.estimated_tokens for item in items) + withheld.estimated_tokens,
        delivered_tokens=delivery.estimated_tokens,
        delivered_chars=len(delivery.rendered),
    )
    failure = (
        AgentContextFailure(
            error_type=delivery.failure.error_type,
            message=delivery.failure.error_message,
        )
        if delivery.failure
        else None
    )
    return ProjectAgentContextResponse(
        project_id=project_id,
        consumer_profile=delivery.metadata.consumer_profile,
        consumer_surface=delivery.metadata.consumer_surface,
        status=delivery.status,
        generated_at=delivery.generated_at,
        items=items,
        withheld=withheld,
        totals=totals,
        failure=failure,
    )


@router.get("/{project_id}/agent-context", response_model=ProjectAgentContextResponse)
async def get_project_agent_context(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    profile: Annotated[str, Query(max_length=100, description="Consumer profile")] = "agent_startup",
    surface: Annotated[str, Query(max_length=100, description="Consumer surface")] = DEFAULT_SURFACE,
) -> ProjectAgentContextResponse:
    """List what a coding agent's startup context contains for this project."""
    if project_id not in await get_registered_project_roots():
        raise HTTPException(status_code=404, detail=f"Unknown project '{project_id}'")
    delivery = await build_canonical_context_delivery(
        db,
        CanonicalContextDeliveryRequest(
            consumer_surface=surface,
            consumer_profile=profile,
            capabilities=list(DEFAULT_CAPABILITIES),
            project_id=project_id,
            phase=DEFAULT_PHASE,
        ),
    )
    return summarize_delivery(delivery, project_id=project_id)
