"""Narrow, revision-checked scope moves for registered service clients."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import check_project_access
from app.models.memory_unified import Memory
from app.services.context_governance import ContextDraft, SourceEdit, apply_draft, preview_draft
from app.services.context_policy import source_policy, source_revision
from app.services.runtime_context import CanonicalContextDeliveryRequest


class MemoryScopePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_id: str = Field(min_length=8)
    scope: Literal["global", "project", "agent"]
    scope_id: str | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_target(self) -> MemoryScopePreviewRequest:
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("A reason is required")
        if self.scope == "global":
            if self.scope_id is not None:
                raise ValueError("Global scope cannot have a scope_id")
        elif not self.scope_id or not self.scope_id.strip() or self.scope_id != self.scope_id.strip():
            raise ValueError("Project and agent scope require one scope_id")
        return self


class MemoryScopeApplyRequest(MemoryScopePreviewRequest):
    expected_revision: str = Field(min_length=1)


async def _resolve_memory(db: AsyncSession, memory_id: str) -> Memory:
    from uuid import UUID

    try:
        canonical = str(UUID(memory_id))
    except ValueError:
        canonical = None
    if canonical is not None and len(memory_id) == 36:
        rows = list((await db.execute(select(Memory).where(Memory.id == UUID(canonical)))).scalars())
    else:
        if any(char not in "0123456789abcdefABCDEF-" for char in memory_id):
            raise HTTPException(422, "Use a memory UUID or unique UUID prefix")
        rows = list((await db.execute(select(Memory).where(cast(Memory.id, String).startswith(memory_id.lower())).limit(2))).scalars())
    if not rows:
        raise HTTPException(404, "Memory not found")
    if len(rows) > 1:
        raise HTTPException(409, "Memory ID prefix is ambiguous; use the complete UUID")
    return rows[0]


def _authorize(client: dict[str, Any], before_scope: str, before_id: str | None,
               target_scope: str, target_id: str | None) -> None:
    kind = client.get("client_type")
    projects = client.get("allowed_projects")
    if kind not in {"internal", "service"}:
        raise HTTPException(403, "Internal or service client required")
    if kind == "service" and not (
        before_scope == target_scope == "project" and before_id == target_id
        and projects is not None and check_project_access(projects, target_id or "")
    ):
        raise HTTPException(403, "Service clients may edit scope within their allowed project only")
    if kind == "internal" and projects is not None:
        if (before_scope != target_scope or before_id != target_id or
            before_scope in {"global", "agent"}) and not check_project_access(projects, "agent-hub"):
            raise HTTPException(403, "Scope moves require Agent Hub administration access")
        for scope, scope_id in ((before_scope, before_id), (target_scope, target_id)):
            if scope == "project" and not check_project_access(projects, scope_id or ""):
                raise HTTPException(403, "Project is outside this client's allowed projects")


async def _prepare(db: AsyncSession, request: MemoryScopePreviewRequest,
                   client: dict[str, Any], *, expected_revision: str | None = None) -> tuple[Memory, ContextDraft, dict[str, str | None]]:
    row = await _resolve_memory(db, request.memory_id)
    policy = source_policy(row)
    before = {"scope": policy.scope, "scope_id": policy.targets[0] if policy.targets else None}
    after = {"scope": request.scope, "scope_id": request.scope_id}
    _authorize(client, policy.scope, before["scope_id"], request.scope, request.scope_id)
    if expected_revision is not None and source_revision(row) != expected_revision:
        raise HTTPException(409, "Memory changed. Reload and review the new revision.")
    if request.scope == "agent":
        from app.services.agent_crud import get_agent_by_slug

        if await get_agent_by_slug(db, request.scope_id or "") is None:
            raise HTTPException(422, "Choose an active registered agent target")
    if before == after:
        raise HTTPException(422, "Memory already has this scope")
    changed_policy = policy.model_copy(update={"scope": request.scope, "targets": [request.scope_id] if request.scope_id else []})
    context = CanonicalContextDeliveryRequest(
        consumer_surface="codex", project_id=request.scope_id if request.scope == "project" else before["scope_id"] if before["scope"] == "project" else None,
        include_project_index=False, include_tool_capabilities=False, include_continuity=False,
    )
    draft = ContextDraft(context=context, edits=[SourceEdit(
        source_type="memory", source_id=str(row.id), expected_revision=source_revision(row), policy=changed_policy,
    )], reason=request.reason)
    return row, draft, before


def _receipt(result: dict[str, Any], memory_id: str, before: dict[str, str | None],
             target: MemoryScopePreviewRequest) -> dict[str, Any]:
    change = result["changes"][0]
    if change["before"]["content"] != change["after"]["content"]:
        raise HTTPException(500, "Scope edit unexpectedly changed memory content")
    return {"memory_id": memory_id, "before": before,
            "after": {"scope": target.scope, "scope_id": target.scope_id},
            "content_unchanged": True}


async def preview_memory_scope(db: AsyncSession, request: MemoryScopePreviewRequest,
                               client: dict[str, Any]) -> dict[str, Any]:
    row, draft, before = await _prepare(db, request, client)
    canonical_id = str(row.id)
    result = await preview_draft(db, draft)
    return {**_receipt(result, canonical_id, before, request),
            "expected_revision": draft.edits[0].expected_revision,
            "token_delta": result["token_delta"]}


async def apply_memory_scope(db: AsyncSession, request: MemoryScopeApplyRequest,
                             client: dict[str, Any]) -> dict[str, Any]:
    row, draft, before = await _prepare(db, request, client, expected_revision=request.expected_revision)
    draft.edits[0].expected_revision = request.expected_revision
    result = await apply_draft(db, draft, f"service:{client['id']}", preview=False)
    return {**_receipt(result, str(row.id), before, request),
            "revision": result["changes"][0]["after_revision"], "change_id": result["change_id"]}
