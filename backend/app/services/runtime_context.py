"""Runtime context profile rendering for external agentic CLIs."""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_unified import Memory
from app.models.prompt import Prompt
from app.models.runtime_context import (
    RuntimeContextOverride,
    RuntimeContextProfilePolicy,
)
from app.services.memory.applicability import (
    applicability_has_exclusions,
    applicability_has_targets,
    applicability_matches,
    normalize_agent_slug,
    normalize_consumer_surface,
    normalize_context_identifier,
    normalize_trigger_phases,
    normalize_trigger_task_types,
)
from app.services.memory.budget import BudgetUsage, count_tokens
from app.services.memory.context_builder import ProgressiveContext, build_progressive_context
from app.services.memory.context_builder_tiers import (
    apply_render_tier,
    get_rendered_content,
    plan_context_render_tiers,
)
from app.services.memory.context_injector_blocks_helpers import episode_to_result
from app.services.memory.context_profiles import (
    _PROFILE_POLICY_LIMITS,
    MemoryConsumerProfile,
    invalidate_policy_cache,
    resolve_consumer_profile,
)
from app.services.memory.project_index_context import format_project_index_context
from app.services.memory.repository import MemoryRepository
from app.services.memory.service import MemoryCategory, MemoryScope, MemorySearchResult
from app.services.memory.settings import get_memory_settings
from app.services.memory.st_usage_memory import decay_score_by_surface
from app.services.memory.tool_capability_context import format_tool_capability_context
from app.services.owned_prompt_service import (
    GLOBAL_GUARDRAIL_PROMPT_TYPE,
    GLOBAL_MANDATE_PROMPT_TYPE,
)
from app.services.project_permission_service import get_visible_tools_for_project

RuntimeSourceType = Literal["prompt", "memory"]
RuntimeOverrideMode = Literal["include", "exclude", "order"]
RuntimeBlockSource = Literal["auto", "pinned"]
RuntimeTierOverride = Literal["L0", "L1", "L2"]
CanonicalDeliveryStatus = Literal["ok", "failed"]
CanonicalPolicyState = Literal["complete", "failed"]

CANONICAL_CONTEXT_SCHEMA_VERSION = "agent-hub.context.v1"
CANONICAL_CONTEXT_VERSION = "1"


class _OverrideLike(Protocol):
    source_type: str
    source_id: str


TOverrideItem = TypeVar("TOverrideItem", bound=_OverrideLike)

KNOWN_RUNTIME_PROFILES = ("agent_startup",)


class RuntimeContextOverridePayload(BaseModel):
    source_type: RuntimeSourceType
    source_id: str
    mode: RuntimeOverrideMode = "include"
    position: int = Field(50, ge=1, le=9999)
    enabled: bool = True
    note: str | None = None
    tier_override: RuntimeTierOverride | None = None


class RuntimeContextOverrideResponse(RuntimeContextOverridePayload):
    id: str
    consumer_profile: str
    project_id: str | None = None


class RuntimeContextBlockResponse(BaseModel):
    id: str
    source_type: RuntimeSourceType
    source_id: str
    title: str
    content: str
    token_count: int
    origin: Literal["auto", "override"]
    # New: explicit "where did this come from" — auto (tier rule / boot_eligible)
    # or pinned (manual include override).
    source: RuntimeBlockSource = "auto"
    # New: short tag explaining auto-injection ("tier:mandate", "boot_eligible", ...).
    # None when source is pinned.
    auto_reason: str | None = None
    mode: RuntimeOverrideMode
    position: int
    tier: str | None = None
    # DB prompt authority type (global_guardrail, global_mandate, standard,
    # runtime_context, ...). Kept separate from memory tier/source type.
    prompt_type: str | None = None
    # Effective L0/L1/L2 render tier for memory blocks (None for prompt blocks).
    render_tier: str | None = None
    # User-set per-memory render preference, surfaced for UI display.
    render_mode: str | None = None
    # Resolved per-profile/per-project tier override, if any.
    tier_override: RuntimeTierOverride | None = None
    # New: where the block lives — "global" or "project:<id>" for memories;
    # "global" for prompts (we don't currently scope prompts per project).
    scope: str | None = None
    scope_id: str | None = None
    # New: free-form tags surfaced for filtering in the library.
    tags: list[str] = Field(default_factory=list)
    # Immutable source revision used by session audits. Memories use their
    # integer row version plus a content hash; prompts use an exact content
    # hash because the prompt table has no mutable version column.
    source_revision: str | None = None
    review_status: str | None = None
    sensitivity_tier: str | None = None


class RuntimeContextPreviewResponse(BaseModel):
    consumer_profile: str
    project_id: str | None
    query: str
    total_tokens: int
    # New: configured budget ceiling for this profile (memory.total_budget).
    budget_tokens: int = 0
    # Whether the configured budget ceiling is active. When false, callers
    # should report the token count without treating budget_tokens as a limit.
    budget_enabled: bool = True
    rendered: str
    blocks: list[RuntimeContextBlockResponse]
    # New: blocks the user has explicitly excluded — surfaced for UI restore.
    excluded: list[RuntimeContextBlockResponse] = Field(default_factory=list)
    overrides: list[RuntimeContextOverrideResponse]
    # Computed boot-context blocks rendered alongside prompts/memories at session
    # start (project_index_block + tool_capability_block in
    # context_injector_ops.finalize_injection). Surfaced separately so the UI
    # can label them; total_tokens already accounts for them.
    project_index: str = ""
    continuity: str = ""
    tool_capabilities: str = ""
    # Deprecated compatibility field. Canonical assembly does not duplicate
    # mandates in a footer.
    non_negotiables: str = ""


class CanonicalContextDeliveryRequest(BaseModel):
    """Metadata and selection inputs for one canonical context delivery."""

    consumer_surface: str = Field(..., min_length=1, max_length=100)
    consumer_profile: str = Field("agent_startup", min_length=1, max_length=100)
    capabilities: list[str] = Field(default_factory=list)
    agent_slug: str | None = Field(None, max_length=100)
    consumer_tags: list[str] = Field(default_factory=list)
    project_id: str | None = Field(None, max_length=100)
    session_id: str | None = Field(None, max_length=200)
    task: str | None = None
    query: str | None = None
    task_type: str | None = Field(None, max_length=100)
    phase: str | None = Field(None, max_length=100)
    current_branch: str | None = Field(None, max_length=200)
    cwd: str | None = None
    repo_root: str | None = None
    provider: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=200)
    include_global: bool = True
    include_prompts: bool = True
    include_memories: bool = True
    include_mandates: bool = True
    include_guardrails: bool = True
    include_references: bool = True
    include_reference_index: bool = True
    exclude_tags: list[str] = Field(default_factory=list)
    exclude_memory_uuids: list[str] = Field(default_factory=list)
    include_project_index: bool = True
    include_tool_capabilities: bool = True
    include_continuity: bool = True
    continuity_max_sessions: int | None = Field(None, ge=1)
    continuity_cross_project: bool = False
    continuity_live_sessions: bool = False
    variant: str | None = Field(None, max_length=100)
    client_metadata: dict[str, str] = Field(default_factory=dict)


class CanonicalContextMetadata(BaseModel):
    """Consumer/session metadata echoed for immutable delivery artifacts."""

    consumer_surface: str
    consumer_profile: str
    capabilities: list[str] = Field(default_factory=list)
    agent_slug: str | None = None
    consumer_tags: list[str] = Field(default_factory=list)
    project_id: str | None = None
    session_id: str | None = None
    task: str | None = None
    query: str
    query_hash: str
    task_type: str | None = None
    phase: str | None = None
    current_branch: str | None = None
    cwd: str | None = None
    repo_root: str | None = None
    provider: str | None = None
    model: str | None = None
    include_global: bool = True
    include_prompts: bool = True
    include_memories: bool = True
    include_mandates: bool = True
    include_guardrails: bool = True
    include_references: bool = True
    include_reference_index: bool = True
    exclude_tags: list[str] = Field(default_factory=list)
    exclude_memory_uuids: list[str] = Field(default_factory=list)
    include_project_index: bool = True
    include_tool_capabilities: bool = True
    include_continuity: bool = True
    continuity_max_sessions: int | None = None
    continuity_cross_project: bool = False
    continuity_live_sessions: bool = False
    variant: str | None = None
    client_metadata: dict[str, str] = Field(default_factory=dict)


class CanonicalContextProvenance(BaseModel):
    """Exact source identity and revision for a delivered block."""

    source_type: Literal["prompt", "memory", "computed"]
    source_id: str
    source_revision: str
    origin: str
    reason: str | None = None
    scope: str | None = None
    scope_id: str | None = None
    review_status: str | None = None
    sensitivity_tier: str | None = None


class CanonicalContextBlock(BaseModel):
    """One ordered operator-owned context block."""

    order: int
    block_id: str
    kind: str
    authority: str
    required: bool
    title: str
    content: str
    estimated_tokens: int
    provenance: CanonicalContextProvenance


class CanonicalPolicyCompleteness(BaseModel):
    """Required-policy retrieval state, independent from optional references."""

    state: CanonicalPolicyState
    required_source_ids: list[str] = Field(default_factory=list)
    delivered_source_ids: list[str] = Field(default_factory=list)
    missing_source_ids: list[str] = Field(default_factory=list)
    pending_review_source_ids: list[str] = Field(default_factory=list)
    operator_excluded_source_ids: list[str] = Field(default_factory=list)


class CanonicalContextFailure(BaseModel):
    operation: str
    error_type: str
    error_message: str


class CanonicalContextPreviewProjection(BaseModel):
    """UI-only projection of the exact canonical selection and computed blocks."""

    blocks: list[RuntimeContextBlockResponse] = Field(default_factory=list)
    excluded: list[RuntimeContextBlockResponse] = Field(default_factory=list)
    overrides: list[RuntimeContextOverrideResponse] = Field(default_factory=list)
    core_rendered: str = ""
    project_index: str = ""
    continuity: str = ""
    tool_capabilities: str = ""
    budget_tokens: int = 0
    budget_enabled: bool = True


class CanonicalRequiredPolicyIncomplete(RuntimeError):
    """Applicable required policy was selected but not delivered."""

    def __init__(
        self,
        *,
        required_source_ids: list[str],
        delivered_source_ids: list[str],
        missing_source_ids: list[str],
    ) -> None:
        self.required_source_ids = required_source_ids
        self.delivered_source_ids = delivered_source_ids
        self.missing_source_ids = missing_source_ids
        super().__init__(
            "Applicable required policy was not delivered: "
            + ", ".join(missing_source_ids)
        )


class CanonicalContextDeliveryResponse(BaseModel):
    """Versioned canonical payload consumed by Agent Hub and thin TUI adapters."""

    schema_version: str = CANONICAL_CONTEXT_SCHEMA_VERSION
    context_version: str = CANONICAL_CONTEXT_VERSION
    delivery_id: str
    artifact_id: str
    generated_at: datetime
    status: CanonicalDeliveryStatus
    delivery_mode: Literal["additive"] = "additive"
    recommended_role: Literal["developer"] = "developer"
    native_context_policy: Literal["preserve"] = "preserve"
    precedence: str = "preserve native harness messages; add operator context without replacement"
    payload_hash_algorithm: Literal["sha256"] = "sha256"
    payload_hash: str
    metadata: CanonicalContextMetadata
    blocks: list[CanonicalContextBlock] = Field(default_factory=list)
    rendered: str
    estimated_tokens: int
    required_policy: CanonicalPolicyCompleteness
    failure: CanonicalContextFailure | None = None
    preview: CanonicalContextPreviewProjection | None = None


@dataclass(frozen=True)
class _ResolvedOverride:
    source_type: str
    source_id: str
    mode: str
    position: int
    enabled: bool
    note: str | None
    project_id: str | None
    id: str
    tier_override: str | None = None


@dataclass(frozen=True)
class _RuntimeContextSelection:
    consumer_profile: str
    project_id: str | None
    query: str
    blocks: list[RuntimeContextBlockResponse]
    excluded: list[RuntimeContextBlockResponse]
    overrides: list[RuntimeContextOverrideResponse]
    project_index: str
    tool_capabilities: str
    budget_tokens: int
    budget_enabled: bool
    expected_required_source_ids: list[str] = field(default_factory=list)
    operator_excluded_required_source_ids: list[str] = field(default_factory=list)


def _override_response(row: RuntimeContextOverride) -> RuntimeContextOverrideResponse:
    return RuntimeContextOverrideResponse(
        id=row.id,
        consumer_profile=row.consumer_profile,
        project_id=row.project_id,
        source_type=row.source_type,
        source_id=row.source_id,
        mode=row.mode,
        position=row.position,
        enabled=row.enabled,
        note=row.note,
        tier_override=row.tier_override,
    )


async def list_runtime_context_overrides(
    db: AsyncSession,
    *,
    consumer_profile: str,
    project_id: str | None,
) -> list[RuntimeContextOverrideResponse]:
    rows = await _load_override_rows(
        db,
        consumer_profile=consumer_profile,
        project_id=project_id,
        include_inherited=False,
    )
    rows = await _filter_live_override_rows(db, rows)
    return [_override_response(row) for row in rows]


async def replace_runtime_context_overrides(
    db: AsyncSession,
    *,
    consumer_profile: str,
    project_id: str | None,
    overrides: list[RuntimeContextOverridePayload],
) -> list[RuntimeContextOverrideResponse]:
    overrides = await _filter_live_override_items(db, overrides)
    await db.execute(
        delete(RuntimeContextOverride).where(
            RuntimeContextOverride.consumer_profile == consumer_profile,
            RuntimeContextOverride.project_id.is_(None)
            if project_id is None
            else RuntimeContextOverride.project_id == project_id,
        )
    )
    rows: list[RuntimeContextOverride] = []
    for item in overrides:
        row = RuntimeContextOverride(
            consumer_profile=consumer_profile,
            project_id=project_id,
            source_type=item.source_type,
            source_id=item.source_id,
            mode=item.mode,
            position=item.position,
            enabled=item.enabled,
            note=item.note,
            tier_override=item.tier_override,
        )
        db.add(row)
        rows.append(row)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return [_override_response(row) for row in rows]


async def render_runtime_context(
    db: AsyncSession,
    *,
    consumer_profile: str,
    project_id: str | None,
    query: str,
    task_type: str | None = None,
    phase: str | None = None,
    include_global: bool = True,
) -> RuntimeContextPreviewResponse:
    """Project the exact canonical delivery into the legacy preview schema."""
    delivery = await build_canonical_context_delivery(
        db,
        CanonicalContextDeliveryRequest(
            consumer_profile=consumer_profile,
            consumer_surface="runtime_context_preview",
            project_id=project_id,
            query=query,
            task_type=task_type,
            phase=phase,
            include_global=include_global,
        ),
    )
    projection = delivery.preview
    if projection is None:
        return RuntimeContextPreviewResponse(
            consumer_profile=delivery.metadata.consumer_profile,
            project_id=delivery.metadata.project_id,
            query=delivery.metadata.query,
            total_tokens=delivery.estimated_tokens,
            budget_enabled=False,
            rendered=delivery.rendered,
            blocks=[],
            overrides=[],
        )
    return RuntimeContextPreviewResponse(
        consumer_profile=delivery.metadata.consumer_profile,
        project_id=delivery.metadata.project_id,
        query=delivery.metadata.query,
        total_tokens=delivery.estimated_tokens,
        budget_tokens=projection.budget_tokens,
        budget_enabled=projection.budget_enabled,
        rendered=projection.core_rendered,
        blocks=projection.blocks,
        excluded=projection.excluded,
        overrides=projection.overrides,
        project_index=projection.project_index,
        continuity=projection.continuity,
        tool_capabilities=projection.tool_capabilities,
        # Kept in the response schema for old UI clients. The duplicate footer
        # is intentionally no longer assembled into canonical context.
        non_negotiables="",
    )


async def _select_runtime_context(
    db: AsyncSession,
    *,
    consumer_profile: str,
    consumer_surface: str,
    project_id: str | None,
    query: str,
    task_type: str | None,
    phase: str | None,
    include_global: bool,
    agent_slug: str | None,
    consumer_tags: list[str],
    include_prompts: bool,
    include_memories: bool,
    include_mandates: bool,
    include_guardrails: bool,
    include_references: bool,
    include_reference_index: bool,
    exclude_tags: list[str],
    exclude_memory_uuids: list[str],
    include_project_index: bool,
    include_tool_capabilities: bool,
    variant: str | None,
) -> _RuntimeContextSelection:
    """Select and order prompts/memory once for previews and real delivery."""
    override_rows = await _load_override_rows(
        db, consumer_profile=consumer_profile, project_id=project_id
    )
    override_rows = await _filter_live_override_rows(db, override_rows)
    overrides = _resolve_overrides(override_rows)
    override_by_key = {
        (item.source_type, item.source_id): item
        for item in overrides
        if item.enabled
    }
    excluded_keys = {
        (item.source_type, item.source_id)
        for item in overrides
        if item.enabled and item.mode == "exclude"
    }

    candidates: list[RuntimeContextBlockResponse] = []
    expected_required_memory_ids: list[str] = []
    if include_prompts:
        candidates.extend(
            await _build_prompt_blocks(
                db,
                overrides,
                override_by_key,
                excluded_keys,
                agent_slug=agent_slug,
                include_mandates=include_mandates,
                include_guardrails=include_guardrails,
            )
        )
    if include_memories:
        candidates.extend(await _build_memory_blocks(
            db,
            consumer_profile=consumer_profile,
            consumer_surface=consumer_surface,
            agent_slug=agent_slug,
            consumer_tags=consumer_tags,
            project_id=project_id,
            query=query,
            task_type=task_type,
            phase=phase,
            include_global=include_global,
            include_mandates=include_mandates,
            include_guardrails=include_guardrails,
            include_references=include_references,
            include_reference_index=include_reference_index,
            exclude_tags=exclude_tags,
            exclude_memory_uuids=exclude_memory_uuids,
            variant=variant,
            overrides=overrides,
            override_by_key=override_by_key,
            excluded=excluded_keys,
            expected_required_source_ids=expected_required_memory_ids,
        ))
    candidates.sort(key=lambda block: (block.position, _source_sort(block.source_type), block.source_id))

    rendered_blocks = [block for block in candidates if block.mode != "exclude"]
    excluded_blocks = [block for block in candidates if block.mode == "exclude"]

    project_index_block, tool_capability_block = await _compute_auxiliary_blocks(
        consumer_profile=consumer_profile,
        agent_slug=agent_slug,
        project_id=project_id,
        task_type=task_type,
        include_project_index=include_project_index,
        include_tool_capabilities=include_tool_capabilities,
    )
    settings = await get_memory_settings(db)
    operator_excluded_required_source_ids = list(
        dict.fromkeys(
            block.source_id
            for block in excluded_blocks
            if block.source_type == "prompt"
            or block.tier in {"mandate", "guardrail"}
        )
    )
    expected_required_source_ids = list(
        dict.fromkeys(
            [
                block.source_id
                for block in candidates
                if block.mode != "exclude"
                and (
                    block.source_type == "prompt"
                    or block.tier in {"mandate", "guardrail"}
                )
            ]
            + [
                source_id
                for source_id in expected_required_memory_ids
                if ("memory", source_id) not in excluded_keys
            ]
        )
    )
    return _RuntimeContextSelection(
        consumer_profile=consumer_profile,
        project_id=project_id,
        query=query,
        budget_tokens=settings.total_budget,
        budget_enabled=settings.budget_enabled,
        blocks=rendered_blocks,
        excluded=excluded_blocks,
        overrides=[_override_response(row) for row in override_rows],
        project_index=project_index_block,
        tool_capabilities=tool_capability_block,
        expected_required_source_ids=expected_required_source_ids,
        operator_excluded_required_source_ids=operator_excluded_required_source_ids,
    )


async def build_canonical_context_delivery(
    db: AsyncSession,
    request: CanonicalContextDeliveryRequest,
) -> CanonicalContextDeliveryResponse:
    """Build the single versioned context contract used by every consumer.

    The response is additive by contract: adapters preserve native harness
    system/safety messages and place ``rendered`` in the strongest additive
    instruction channel their client supports. Token counts are diagnostic;
    this path does not trim or reject context based on size.
    """
    delivery_id = str(uuid.uuid4())
    effective_request = _normalize_canonical_request(request)
    query = _resolve_canonical_query(effective_request)
    metadata = _canonical_metadata(effective_request, query)

    try:
        resolved_project_id = await _resolve_canonical_project_id(effective_request)
        if resolved_project_id != effective_request.project_id:
            effective_request = effective_request.model_copy(
                update={"project_id": resolved_project_id}
            )
            metadata = _canonical_metadata(effective_request, query)

        selection = await _select_runtime_context(
            db,
            consumer_profile=effective_request.consumer_profile,
            consumer_surface=effective_request.consumer_surface,
            agent_slug=effective_request.agent_slug,
            consumer_tags=effective_request.consumer_tags,
            project_id=effective_request.project_id,
            query=query,
            task_type=effective_request.task_type,
            phase=effective_request.phase,
            include_global=effective_request.include_global,
            include_prompts=effective_request.include_prompts,
            include_memories=effective_request.include_memories,
            include_mandates=effective_request.include_mandates,
            include_guardrails=effective_request.include_guardrails,
            include_references=effective_request.include_references,
            include_reference_index=effective_request.include_reference_index,
            exclude_tags=effective_request.exclude_tags,
            exclude_memory_uuids=effective_request.exclude_memory_uuids,
            include_project_index=effective_request.include_project_index,
            include_tool_capabilities=effective_request.include_tool_capabilities,
            variant=effective_request.variant,
        )

        continuity = ""
        if effective_request.project_id and effective_request.include_continuity:
            from app.services.memory.continuity_injector import (
                build_continuity_context,
            )

            settings = await get_memory_settings(db)
            if settings.continuity_enabled:
                continuity_context = await build_continuity_context(
                    project_id=effective_request.project_id,
                    current_branch=effective_request.current_branch,
                    max_sessions=(
                        effective_request.continuity_max_sessions
                        or settings.continuity_max_sessions
                    ),
                    include_cross_project=(
                        effective_request.continuity_cross_project
                    ),
                    include_live_sessions=(
                        effective_request.continuity_live_sessions
                    ),
                    exclude_session_id=effective_request.session_id,
                )
                continuity = continuity_context.markdown.strip()

        ordered_runtime_blocks = _order_runtime_blocks_for_delivery(
            selection.blocks
        )
        blocks = _build_canonical_blocks(selection, continuity)
        core_rendered = _render_blocks(ordered_runtime_blocks)
        rendered = "\n".join(
            chunk
            for chunk in (
                core_rendered,
                selection.project_index,
                continuity,
                selection.tool_capabilities,
            )
            if chunk
        )
        payload_hash = _sha256_text(rendered)
        required_blocks = [block for block in blocks if block.required]
        delivered_required_ids = list(
            dict.fromkeys(block.provenance.source_id for block in required_blocks)
        )
        required_ids = list(
            dict.fromkeys(
                [*selection.expected_required_source_ids, *delivered_required_ids]
            )
        )
        missing_required_ids = [
            source_id
            for source_id in required_ids
            if source_id not in set(delivered_required_ids)
        ]
        if missing_required_ids:
            raise CanonicalRequiredPolicyIncomplete(
                required_source_ids=required_ids,
                delivered_source_ids=delivered_required_ids,
                missing_source_ids=missing_required_ids,
            )
        pending_review = [
            block.provenance.source_id
            for block in required_blocks
            if block.provenance.source_type == "memory"
            and block.provenance.review_status != "clean"
        ]
        return CanonicalContextDeliveryResponse(
            delivery_id=delivery_id,
            artifact_id=f"context-{payload_hash}",
            generated_at=datetime.now(UTC),
            status="ok",
            payload_hash=payload_hash,
            metadata=metadata,
            blocks=blocks,
            rendered=rendered,
            estimated_tokens=count_tokens(rendered),
            required_policy=CanonicalPolicyCompleteness(
                state="complete",
                required_source_ids=required_ids,
                delivered_source_ids=delivered_required_ids,
                pending_review_source_ids=pending_review,
                operator_excluded_source_ids=(
                    selection.operator_excluded_required_source_ids
                ),
            ),
            preview=CanonicalContextPreviewProjection(
                blocks=ordered_runtime_blocks,
                excluded=selection.excluded,
                overrides=selection.overrides,
                core_rendered=core_rendered,
                project_index=selection.project_index,
                continuity=continuity,
                tool_capabilities=selection.tool_capabilities,
                budget_tokens=selection.budget_tokens,
                budget_enabled=selection.budget_enabled,
            ),
        )
    except Exception as exc:
        return _build_canonical_failure_response(
            delivery_id=delivery_id,
            metadata=metadata,
            error=exc,
        )


def _resolve_canonical_query(request: CanonicalContextDeliveryRequest) -> str:
    return (request.query or request.task or "startup context").strip() or "startup context"


def _normalize_canonical_request(
    request: CanonicalContextDeliveryRequest,
) -> CanonicalContextDeliveryRequest:
    """Normalize all applicability identifiers at the canonical boundary."""
    task_type = normalize_trigger_task_types(
        [request.task_type] if request.task_type else []
    )
    phases = normalize_trigger_phases([request.phase] if request.phase else [])
    return request.model_copy(
        update={
            "consumer_surface": normalize_consumer_surface(request.consumer_surface)
            or "agent_runtime",
            "consumer_profile": resolve_consumer_profile(
                request.consumer_profile
            ).value,
            "capabilities": list(
                dict.fromkeys(
                    normalized
                    for capability in request.capabilities
                    if (normalized := normalize_context_identifier(capability))
                )
            ),
            "agent_slug": normalize_agent_slug(request.agent_slug),
            "consumer_tags": list(
                dict.fromkeys(
                    tag.strip().lower()
                    for tag in request.consumer_tags
                    if tag.strip()
                )
            ),
            "task_type": task_type[0] if task_type else None,
            "phase": phases[0] if phases else None,
            "exclude_tags": list(
                dict.fromkeys(
                    tag.strip().lower()
                    for tag in request.exclude_tags
                    if tag.strip()
                )
            ),
        }
    )


async def _resolve_canonical_project_id(
    request: CanonicalContextDeliveryRequest,
) -> str | None:
    """Resolve project identity only through the canonical project registry."""
    from app.core.project_roots import get_registered_project_roots

    raw_paths = [
        path
        for path in (request.repo_root, request.cwd)
        if path and path.strip()
    ]
    if not request.project_id and not raw_paths:
        return None

    registered_roots = await get_registered_project_roots()
    if request.project_id:
        if request.project_id not in registered_roots:
            raise ValueError(
                f"Unknown project_id '{request.project_id}'. "
                f"Registered projects: {sorted(registered_roots)}"
            )
        return request.project_id
    candidate_paths = [
        os.path.realpath(os.path.expanduser(path))
        for path in raw_paths
    ]

    matches: list[tuple[int, str]] = []
    for project_id, raw_root in registered_roots.items():
        root = os.path.realpath(os.path.expanduser(raw_root))
        for candidate in candidate_paths:
            try:
                if os.path.commonpath((candidate, root)) == root:
                    matches.append((len(root), project_id))
                    break
            except ValueError:
                continue
    if not matches:
        return None
    return max(matches, key=lambda item: (item[0], item[1]))[1]


def _canonical_metadata(
    request: CanonicalContextDeliveryRequest,
    query: str,
) -> CanonicalContextMetadata:
    return CanonicalContextMetadata(
        consumer_surface=request.consumer_surface.strip(),
        consumer_profile=request.consumer_profile.strip(),
        capabilities=list(dict.fromkeys(capability.strip() for capability in request.capabilities if capability.strip())),
        agent_slug=request.agent_slug,
        consumer_tags=list(
            dict.fromkeys(tag.strip() for tag in request.consumer_tags if tag.strip())
        ),
        project_id=request.project_id,
        session_id=request.session_id,
        task=request.task,
        query=query,
        query_hash=_sha256_text(query),
        task_type=request.task_type,
        phase=request.phase,
        current_branch=request.current_branch,
        cwd=request.cwd,
        repo_root=request.repo_root,
        provider=request.provider,
        model=request.model,
        include_global=request.include_global,
        include_prompts=request.include_prompts,
        include_memories=request.include_memories,
        include_mandates=request.include_mandates,
        include_guardrails=request.include_guardrails,
        include_references=request.include_references,
        include_reference_index=request.include_reference_index,
        exclude_tags=list(dict.fromkeys(tag.strip() for tag in request.exclude_tags if tag.strip())),
        exclude_memory_uuids=list(
            dict.fromkeys(
                source_id.strip()
                for source_id in request.exclude_memory_uuids
                if source_id.strip()
            )
        ),
        include_project_index=request.include_project_index,
        include_tool_capabilities=request.include_tool_capabilities,
        include_continuity=request.include_continuity,
        continuity_max_sessions=request.continuity_max_sessions,
        continuity_cross_project=request.continuity_cross_project,
        continuity_live_sessions=request.continuity_live_sessions,
        variant=request.variant,
        client_metadata=dict(sorted(request.client_metadata.items())),
    )


def _build_canonical_blocks(
    selection: _RuntimeContextSelection,
    continuity: str,
) -> list[CanonicalContextBlock]:
    blocks: list[CanonicalContextBlock] = []

    def add_computed(
        *,
        block_id: str,
        kind: str,
        authority: str,
        title: str,
        content: str,
        reason: str,
    ) -> None:
        if not content:
            return
        revision = f"sha256:{_sha256_text(content)}"
        blocks.append(
            CanonicalContextBlock(
                order=len(blocks),
                block_id=block_id,
                kind=kind,
                authority=authority,
                required=False,
                title=title,
                content=content,
                estimated_tokens=count_tokens(content),
                provenance=CanonicalContextProvenance(
                    source_type="computed",
                    source_id=block_id,
                    source_revision=revision,
                    origin="canonical_assembler",
                    reason=reason,
                    scope="project" if selection.project_id else "global",
                    scope_id=selection.project_id,
                ),
            )
        )

    for runtime_block in _order_runtime_blocks_for_delivery(selection.blocks):
        kind = _canonical_block_kind(runtime_block)
        required = runtime_block.source_type == "prompt" or kind in {"mandate", "guardrail"}
        blocks.append(
            CanonicalContextBlock(
                order=len(blocks),
                block_id=runtime_block.id,
                kind=kind,
                authority=_canonical_authority(runtime_block),
                required=required,
                title=runtime_block.title,
                content=runtime_block.content,
                estimated_tokens=runtime_block.token_count,
                provenance=CanonicalContextProvenance(
                    source_type=runtime_block.source_type,
                    source_id=runtime_block.source_id,
                    source_revision=runtime_block.source_revision
                    or f"sha256:{_sha256_text(runtime_block.content)}",
                    origin=runtime_block.origin,
                    reason=runtime_block.auto_reason or runtime_block.mode,
                    scope=runtime_block.scope,
                    scope_id=runtime_block.scope_id,
                    review_status=runtime_block.review_status,
                    sensitivity_tier=runtime_block.sensitivity_tier,
                ),
            )
        )

    add_computed(
        block_id=f"project-index:{selection.project_id or 'global'}",
        kind="project_index",
        authority="project_context",
        title="Project Index",
        content=selection.project_index,
        reason="canonical_project_index",
    )
    add_computed(
        block_id=f"continuity:{selection.project_id or 'global'}",
        kind="continuity",
        authority="advisory_continuity",
        title="Continuity",
        content=continuity,
        reason="canonical_continuity",
    )

    add_computed(
        block_id=f"tool-capabilities:{selection.consumer_profile}:{selection.project_id or 'global'}",
        kind="tool_capabilities",
        authority="capability_reference",
        title="Tool Capabilities",
        content=selection.tool_capabilities,
        reason="canonical_tool_capabilities",
    )
    return blocks


def _canonical_authority(block: RuntimeContextBlockResponse) -> str:
    if block.source_type == "prompt":
        if block.prompt_type == GLOBAL_GUARDRAIL_PROMPT_TYPE:
            return "operator_guardrail"
        if block.prompt_type == GLOBAL_MANDATE_PROMPT_TYPE:
            return "operator_mandate"
        return "operator_instruction"
    return {
        "mandate": "operator_mandate",
        "guardrail": "operator_guardrail",
        "capability": "capability_reference",
        "reference": "advisory_reference",
        "archive": "advisory_reference",
    }.get(block.tier or "", "advisory_reference")


def _order_runtime_blocks_for_delivery(
    blocks: list[RuntimeContextBlockResponse],
) -> list[RuntimeContextBlockResponse]:
    """Order by authority first; UI positions only reorder within a rank."""
    authority_rank = {
        "operator_guardrail": 0,
        "operator_mandate": 1,
        "operator_instruction": 2,
        "capability_reference": 3,
        "advisory_reference": 3,
    }
    return sorted(
        blocks,
        key=lambda block: (
            authority_rank.get(_canonical_authority(block), 4),
            block.position,
            _source_sort(block.source_type),
            block.source_id,
        ),
    )


def _canonical_block_kind(block: RuntimeContextBlockResponse) -> str:
    """Preserve prompt authority type while retaining prompt provenance."""
    if block.source_type == "prompt":
        if block.prompt_type and block.prompt_type != "standard":
            return block.prompt_type
        return "prompt"
    return block.tier or block.source_type


def _build_canonical_failure_response(
    *,
    delivery_id: str,
    metadata: CanonicalContextMetadata,
    error: Exception,
) -> CanonicalContextDeliveryResponse:
    rendered = (
        "<agent-hub-context-failure>\n"
        "Agent Hub canonical supplemental context is unavailable and was not injected. "
        "The consumer must apply its configured failure policy and report degraded "
        "context status to the operator.\n"
        f"{type(error).__name__}: {error}\n"
        "</agent-hub-context-failure>"
    )
    payload_hash = _sha256_text(rendered)
    completeness = (
        CanonicalPolicyCompleteness(
            state="failed",
            required_source_ids=error.required_source_ids,
            delivered_source_ids=error.delivered_source_ids,
            missing_source_ids=error.missing_source_ids,
        )
        if isinstance(error, CanonicalRequiredPolicyIncomplete)
        else CanonicalPolicyCompleteness(state="failed")
    )
    return CanonicalContextDeliveryResponse(
        delivery_id=delivery_id,
        artifact_id=f"context-{payload_hash}",
        generated_at=datetime.now(UTC),
        status="failed",
        payload_hash=payload_hash,
        metadata=metadata,
        blocks=[],
        rendered=rendered,
        estimated_tokens=count_tokens(rendered),
        required_policy=completeness,
        failure=CanonicalContextFailure(
            operation="canonical-context-delivery",
            error_type=type(error).__name__,
            error_message=str(error),
        ),
    )


def _sha256_text(value: str) -> str:
    """Return lowercase SHA-256 hex for the exact UTF-8 bytes supplied."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _compute_auxiliary_blocks(
    *,
    consumer_profile: str,
    agent_slug: str | None,
    project_id: str | None,
    task_type: str | None,
    include_project_index: bool,
    include_tool_capabilities: bool,
) -> tuple[str, str]:
    """Mirror context_injector_ops.run_injection_operation auxiliary blocks.

    The frontend preview must match what an agent actually receives at
    session start: authority-ordered prompts/memory first, followed by these
    computed project and capability blocks.
    """
    project_index_block = (
        await asyncio.to_thread(
            format_project_index_context,
            project_id,
            consumer_profile=consumer_profile,
            task_type=task_type,
        )
        if include_project_index
        else ""
    )
    if not include_tool_capabilities:
        return project_index_block, ""
    visible_tool_names = (
        await get_visible_tools_for_project(project_id) if project_id else frozenset()
    )
    bash_available = ("bash" in visible_tool_names) if project_id else None
    # Usage-weighted adaptive tool selection for startup: score the project's st
    # telemetry and let the manifest curate floor + relevant surfaces. Any failure
    # yields no scores, and format_tool_capability_context falls back to full.
    tool_scores: dict[str, float] | None = None
    if project_id and resolve_consumer_profile(consumer_profile) == MemoryConsumerProfile.AGENT_STARTUP:
        try:
            tool_scores = await decay_score_by_surface(project_id) or None
        except Exception:
            tool_scores = None
    tool_capability_block = await asyncio.to_thread(
        format_tool_capability_context,
        consumer_profile=consumer_profile,
        task_type=task_type,
        project_id=project_id,
        bash_available=bash_available,
        agent_slug=agent_slug,
        tool_scores=tool_scores,
    )
    return project_index_block, tool_capability_block


async def _filter_live_override_rows(
    db: AsyncSession,
    rows: list[RuntimeContextOverride],
) -> list[RuntimeContextOverride]:
    return await _filter_live_override_items(db, rows)


async def _filter_live_override_items(
    db: AsyncSession,
    items: list[TOverrideItem],
) -> list[TOverrideItem]:
    """Drop overrides whose source no longer exists in the active catalog."""
    if not items:
        return items

    prompt_ids = {
        str(item.source_id)
        for item in items
        if item.source_type == "prompt" and item.source_id
    }
    memory_ids: dict[str, uuid.UUID] = {}
    for item in items:
        if item.source_type != "memory":
            continue
        if not item.source_id:
            continue
        try:
            memory_ids[str(item.source_id)] = uuid.UUID(str(item.source_id))
        except (TypeError, ValueError):
            continue

    live_keys: set[tuple[str, str]] = set()
    if prompt_ids:
        prompt_result = await db.execute(
            select(Prompt.slug).where(
                Prompt.enabled.is_(True), Prompt.slug.in_(list(prompt_ids))
            )
        )
        live_keys.update(("prompt", slug) for slug in prompt_result.scalars().all())
    if memory_ids:
        memory_result = await db.execute(
            select(Memory.id).where(
                Memory.id.in_(list(memory_ids.values())), Memory.status == "active"
            )
        )
        live_keys.update(
            ("memory", str(memory_id)) for memory_id in memory_result.scalars().all()
        )

    filtered: list[TOverrideItem] = []
    for item in items:
        source_type = item.source_type
        source_id = item.source_id
        if source_type == "memory":
            try:
                source_id = str(uuid.UUID(str(source_id)))
            except (TypeError, ValueError):
                continue
        if (source_type, source_id) in live_keys:
            filtered.append(item)
    return filtered


async def _load_override_rows(
    db: AsyncSession,
    *,
    consumer_profile: str,
    project_id: str | None,
    include_inherited: bool = True,
) -> list[RuntimeContextOverride]:
    filters = [RuntimeContextOverride.consumer_profile == consumer_profile]
    if project_id and include_inherited:
        filters.append(
            or_(
                RuntimeContextOverride.project_id.is_(None),
                RuntimeContextOverride.project_id == project_id,
            )
        )
    elif project_id:
        filters.append(RuntimeContextOverride.project_id == project_id)
    else:
        filters.append(RuntimeContextOverride.project_id.is_(None))
    result = await db.execute(
        select(RuntimeContextOverride)
        .where(*filters)
        .order_by(RuntimeContextOverride.position.asc(), RuntimeContextOverride.created_at.asc())
    )
    return list(result.scalars().all())


def _resolve_overrides(rows: list[RuntimeContextOverride]) -> list[_ResolvedOverride]:
    resolved: dict[tuple[str, str], _ResolvedOverride] = {}
    for row in rows:
        key = (row.source_type, row.source_id)
        current = resolved.get(key)
        if current and current.project_id and row.project_id is None:
            continue
        resolved[key] = _ResolvedOverride(
            source_type=row.source_type,
            source_id=row.source_id,
            mode=row.mode,
            position=row.position,
            enabled=row.enabled,
            note=row.note,
            project_id=row.project_id,
            id=row.id,
            tier_override=row.tier_override,
        )
    return list(resolved.values())


async def _build_prompt_blocks(
    db: AsyncSession,
    overrides: list[_ResolvedOverride],
    override_by_key: dict[tuple[str, str], _ResolvedOverride],
    excluded: set[tuple[str, str]],
    *,
    agent_slug: str | None = None,
    include_mandates: bool = True,
    include_guardrails: bool = True,
) -> list[RuntimeContextBlockResponse]:
    pinned_slugs = {
        item.source_id
        for item in overrides
        if item.enabled and item.source_type == "prompt" and item.mode == "include"
    }
    # ``Prompt.is_global`` is the ownership contract: every enabled global DB
    # prompt applies to every agent unless explicitly excluded. Runtime
    # overrides may additionally pin a non-global prompt for this profile.
    stmt = select(Prompt).where(Prompt.enabled.is_(True)).where(
        or_(Prompt.is_global.is_(True), Prompt.slug.in_(list(pinned_slugs)))
        if pinned_slugs
        else Prompt.is_global.is_(True)
    )
    result = await db.execute(stmt)
    prompts = list(result.scalars().all())

    blocks: list[RuntimeContextBlockResponse] = []
    for prompt in prompts:
        key = ("prompt", prompt.slug)
        ovr = override_by_key.get(key)
        is_pinned = bool(ovr and ovr.mode == "include")
        if not prompt.is_global and not is_pinned:
            # Agent-owned/assigned prompts are appended by the internal-agent
            # prompt stack. They are never shared operator startup context.
            continue
        if not prompt.is_global and (
            prompt.owner_agent_id is not None
            or ovr is None
            or ovr.project_id is None
        ):
            # Only operator-owned prompts may be promoted into shared context,
            # and that promotion must be explicit for one project. Agent-owned
            # prompts remain solely in the agent prompt stack.
            continue
        if agent_slug and agent_slug in (prompt.exclude_agents or []):
            continue
        if prompt.prompt_type == GLOBAL_MANDATE_PROMPT_TYPE and not include_mandates:
            continue
        if prompt.prompt_type == GLOBAL_GUARDRAIL_PROMPT_TYPE and not include_guardrails:
            continue
        is_excluded = key in excluded
        position = ovr.position if ovr else _default_prompt_position(prompt)
        tags = []
        if prompt.prompt_type and prompt.prompt_type != "standard":
            tags.append(prompt.prompt_type)
        scope = "global" if prompt.is_global else "project"
        blocks.append(
            RuntimeContextBlockResponse(
                id=f"prompt:{prompt.slug}",
                source_type="prompt",
                source_id=prompt.slug,
                title=prompt.name,
                content=prompt.content,
                token_count=count_tokens(prompt.content),
                origin="override" if is_pinned else "auto",
                source="pinned" if is_pinned else "auto",
                auto_reason=None if is_pinned else "global",
                mode="exclude" if is_excluded else ("include" if is_pinned else "order"),
                position=position,
                prompt_type=prompt.prompt_type,
                scope=scope,
                scope_id=None if prompt.is_global else ovr.project_id if ovr else None,
                tags=tags,
                source_revision=f"sha256:{_sha256_text(prompt.content)}",
            )
        )
    blocks.sort(key=lambda block: (block.position, block.source_id))
    return blocks


async def _build_memory_blocks(
    db: AsyncSession,
    *,
    consumer_profile: str,
    consumer_surface: str,
    agent_slug: str | None,
    consumer_tags: list[str],
    project_id: str | None,
    query: str,
    task_type: str | None,
    phase: str | None,
    include_global: bool,
    include_mandates: bool,
    include_guardrails: bool,
    include_references: bool,
    include_reference_index: bool,
    exclude_tags: list[str],
    exclude_memory_uuids: list[str],
    variant: str | None,
    overrides: list[_ResolvedOverride],
    override_by_key: dict[tuple[str, str], _ResolvedOverride],
    excluded: set[tuple[str, str]],
    expected_required_source_ids: list[str] | None = None,
) -> list[RuntimeContextBlockResponse]:
    scope = MemoryScope.PROJECT if project_id else MemoryScope.GLOBAL
    context = await build_progressive_context(
        query=query,
        scope=scope,
        scope_id=project_id,
        include_mandates=include_mandates,
        include_guardrails=include_guardrails,
        include_references=include_references,
        include_global=include_global,
        task_type=task_type,
        phase=phase,
        memory_config={
            "include_mandates": include_mandates,
            "include_guardrails": include_guardrails,
            "include_references": include_references,
            "reference_index_enabled": include_reference_index,
            "audience_tags": consumer_tags,
            "exclude_tags": exclude_tags,
            "exclude_memory_uuids": exclude_memory_uuids,
        },
        consumer_surface=consumer_surface,
        consumer_profile=consumer_profile,
        consumer_agent_slug=agent_slug,
        consumer_tags=consumer_tags,
        variant=variant,
        preserve_required_policy=True,
        db=db,
    )
    if expected_required_source_ids is not None:
        expected_required_source_ids.extend(
            str(source_id)
            for source_id in context.debug_info.get(
                "expected_required_memory_ids", []
            )
            if source_id
        )
    auto_items = [
        *[(item, "mandate", index) for index, item in enumerate(context.mandates)],
        *[(item, "guardrail", index) for index, item in enumerate(context.guardrails)],
        *[(item, "capability", index) for index, item in enumerate(context.reference_index)],
        *[(item, "reference", index) for index, item in enumerate(context.reference)],
    ]
    selected = {item.uuid for item, _, _ in auto_items}
    forced_ids = [
        item.source_id
        for item in overrides
        if item.enabled and item.source_type == "memory" and item.mode == "include"
        and item.source_id not in selected
    ]
    forced_items = await _fetch_forced_memory_items(
        db,
        forced_ids,
        project_id=project_id,
        include_global=include_global,
        include_mandates=include_mandates,
        include_guardrails=include_guardrails,
        include_references=include_references,
        exclude_tags=exclude_tags,
        exclude_memory_uuids=exclude_memory_uuids,
        consumer_surface=consumer_surface,
        consumer_profile=consumer_profile,
        consumer_agent_slug=agent_slug,
        consumer_tags=consumer_tags,
    )
    forced_uuids = {item.uuid for item in forced_items}
    auto_items.extend((item, _tier_for_memory(item), 0) for item in forced_items)

    # Apply per-profile/per-project tier overrides before reading rendered content.
    for item, block_tier, _index in auto_items:
        ovr = override_by_key.get(("memory", item.uuid))
        if block_tier in {"mandate", "guardrail"}:
            apply_render_tier(item, "L2", "canonical_required_policy")
        elif ovr and ovr.tier_override:
            apply_render_tier(item, ovr.tier_override, "user_override")

    memory_revisions = await _load_memory_source_revisions(
        db, [item.uuid for item, _tier, _index in auto_items if item.uuid]
    )

    blocks: list[RuntimeContextBlockResponse] = []
    for item, tier, index in auto_items:
        key = ("memory", item.uuid)
        override = override_by_key.get(key)
        is_excluded = key in excluded
        is_pinned = item.uuid in forced_uuids or bool(
            override and override.mode == "include"
        )
        content = get_rendered_content(item)
        position = override.position if override else _default_memory_position(tier, item, index)
        scope_value = item.scope.value if item.scope else None
        memory_scope = scope_value or "global"
        memory_scope_id = getattr(item, "scope_id", None)
        blocks.append(
            RuntimeContextBlockResponse(
                id=f"memory:{item.uuid}",
                source_type="memory",
                source_id=item.uuid,
                title=item.summary or item.content.splitlines()[0][:80],
                content=content,
                token_count=count_tokens(content),
                origin="override" if is_pinned else "auto",
                source="pinned" if is_pinned else "auto",
                auto_reason=None if is_pinned else f"tier:{tier}",
                mode="exclude" if is_excluded else (override.mode if override else "order"),
                position=position,
                tier=tier,
                render_tier=item.render_tier,
                render_mode=item.render_mode,
                tier_override=override.tier_override if override else None,
                scope=memory_scope,
                scope_id=memory_scope_id,
                tags=list(item.tags or []),
                source_revision=memory_revisions.get(
                    item.uuid, f"sha256:{_sha256_text(item.content)}"
                ),
                review_status=item.review_status,
                sensitivity_tier=item.sensitivity_tier,
            )
        )
    return blocks


async def _load_memory_source_revisions(
    db: AsyncSession,
    source_ids: list[str],
) -> dict[str, str]:
    """Return exact mutable-row versions plus hashes for selected memories."""
    parsed_ids: list[uuid.UUID] = []
    for source_id in source_ids:
        try:
            parsed_ids.append(uuid.UUID(source_id))
        except (TypeError, ValueError):
            continue
    if not parsed_ids:
        return {}
    result = await db.execute(
        select(Memory.id, Memory.version, Memory.content).where(Memory.id.in_(parsed_ids))
    )
    return {
        str(memory_id): f"v{version}:sha256:{_sha256_text(content)}"
        for memory_id, version, content in result.all()
    }


async def _fetch_forced_memory_items(
    db: AsyncSession,
    source_ids: list[str],
    *,
    project_id: str | None,
    include_global: bool,
    include_mandates: bool,
    include_guardrails: bool,
    include_references: bool,
    exclude_tags: list[str],
    exclude_memory_uuids: list[str],
    consumer_surface: str,
    consumer_profile: str,
    consumer_agent_slug: str | None,
    consumer_tags: list[str],
) -> list[MemorySearchResult]:
    """Load pinned memories without bypassing canonical eligibility rules."""
    parsed_ids: list[uuid.UUID] = []
    for source_id in source_ids:
        try:
            parsed_ids.append(uuid.UUID(source_id))
        except ValueError:
            continue
    if not parsed_ids:
        return []
    result = await db.execute(
        select(Memory).where(Memory.id.in_(parsed_ids), Memory.status == "active")
    )
    items: list[MemorySearchResult] = []
    for memory in result.scalars().all():
        item = episode_to_result(MemoryRepository._to_dict(memory))
        if item and _forced_memory_item_matches(
            item,
            project_id=project_id,
            include_global=include_global,
            include_mandates=include_mandates,
            include_guardrails=include_guardrails,
            include_references=include_references,
            exclude_tags=exclude_tags,
            exclude_memory_uuids=exclude_memory_uuids,
            consumer_surface=consumer_surface,
            consumer_profile=consumer_profile,
            consumer_agent_slug=consumer_agent_slug,
            consumer_tags=consumer_tags,
        ):
            items.append(item)
    return items


def _forced_memory_item_matches(
    item: MemorySearchResult,
    *,
    project_id: str | None,
    include_global: bool,
    include_mandates: bool,
    include_guardrails: bool,
    include_references: bool,
    exclude_tags: list[str],
    exclude_memory_uuids: list[str],
    consumer_surface: str,
    consumer_profile: str,
    consumer_agent_slug: str | None,
    consumer_tags: list[str],
) -> bool:
    if item.uuid in set(exclude_memory_uuids):
        return False
    item_tags = {tag.strip().lower() for tag in item.tags or [] if tag.strip()}
    if item_tags.intersection(tag.strip().lower() for tag in exclude_tags):
        return False

    if item.scope == MemoryScope.PROJECT:
        if not project_id or item.scope_id != project_id:
            return False
    elif not include_global:
        return False

    tier = _tier_for_memory(item)
    if tier == "mandate" and not include_mandates:
        return False
    if tier == "guardrail" and not include_guardrails:
        return False
    if tier not in {"mandate", "guardrail"} and not include_references:
        return False

    if not applicability_matches(
        item.applicability,
        consumer_surface=consumer_surface,
        consumer_profile=consumer_profile,
        consumer_agent_slug=consumer_agent_slug,
        consumer_tags=consumer_tags,
    ):
        return False
    return not (
        tier not in {"mandate", "guardrail"}
        and consumer_tags
        and not applicability_has_targets(item.applicability)
        and not applicability_has_exclusions(item.applicability)
        and not item_tags.intersection(tag.strip().lower() for tag in consumer_tags)
    )


def _tier_for_memory(item: MemorySearchResult) -> str:
    if item.category in {
        MemoryCategory.MANDATE,
        MemoryCategory.GUARDRAIL,
        MemoryCategory.REFERENCE,
        MemoryCategory.ARCHIVE,
    }:
        return item.category.value
    if item.context_kind.value == "capability":
        return "capability"
    return "reference"


def _default_memory_position(tier: str, item: MemorySearchResult, index: int) -> int:
    base = {
        "mandate": 1000,
        "guardrail": 2000,
        "capability": 3000,
        "reference": 4000,
    }.get(tier, 5000)
    return base + item.display_order + index


def _default_prompt_position(prompt: Prompt) -> int:
    """Order global prompt authority stably, independent of DB insertion IDs."""
    return {
        GLOBAL_GUARDRAIL_PROMPT_TYPE: 100,
        GLOBAL_MANDATE_PROMPT_TYPE: 200,
        "standard": 300,
        "runtime_context": 300,
    }.get(prompt.prompt_type or "standard", 400)


def _source_sort(source_type: str) -> int:
    return 0 if source_type == "prompt" else 1


async def apply_tier_overrides_to_context(
    db: AsyncSession,
    *,
    consumer_profile: str | None,
    project_id: str | None,
    items: Iterable[MemorySearchResult],
) -> None:
    """Re-tier MemorySearchResults using per-profile runtime overrides.

    Used by both the runtime-context HTTP path (frontend preview) and the
    in-process CLI path (SessionStart hook -> memory-client -> progressive
    context CLI) so that user-set tier overrides reach every consumer.

    No-ops when consumer_profile is None or no override carries a
    tier_override for any of the items.
    """
    if not consumer_profile:
        return
    items_list = list(items)
    if not items_list:
        return
    rows = await _load_override_rows(
        db, consumer_profile=consumer_profile, project_id=project_id
    )
    if not rows:
        return
    by_id = {item.uuid: item for item in items_list if item and item.uuid}
    for ovr in _resolve_overrides(rows):
        if not ovr.enabled or ovr.source_type != "memory" or not ovr.tier_override:
            continue
        target = by_id.get(ovr.source_id)
        if target is not None:
            apply_render_tier(target, ovr.tier_override, "user_override")


async def apply_runtime_memory_overrides_to_context(
    db: AsyncSession | None,
    *,
    consumer_profile: str | None,
    project_id: str | None,
    query: str,
    context: ProgressiveContext,
) -> ProgressiveContext:
    """Apply canonical runtime-context memory overrides to a ProgressiveContext.

    This is the shared bridge between the Runtime Context UI and non-UI
    progressive-context consumers (Agent Hub agents, MCP, and the progressive
    context CLI). The UI persists rows in ``runtime_context_overrides``; this
    function makes the same per-profile/per-project include/exclude/render
    decisions affect the actual memory context delivered to agents.
    """
    if not consumer_profile:
        return context
    if db is None:
        from app.db import async_session

        async with async_session() as session:
            return await apply_runtime_memory_overrides_to_context(
                session,
                consumer_profile=consumer_profile,
                project_id=project_id,
                query=query,
                context=context,
            )

    rows = await _load_override_rows(
        db, consumer_profile=consumer_profile, project_id=project_id
    )
    rows = await _filter_live_override_rows(db, rows)
    overrides = [
        item
        for item in _resolve_overrides(rows)
        if item.enabled and item.source_type == "memory"
    ]
    if not overrides:
        return context

    excluded_ids = {
        item.source_id for item in overrides if item.mode == "exclude"
    }
    _drop_memory_ids(context, excluded_ids)

    loaded_ids = set(context.get_loaded_uuids())
    forced_ids = [
        item.source_id
        for item in overrides
        if item.mode == "include"
        and item.source_id not in loaded_ids
        and item.source_id not in excluded_ids
    ]
    forced_items = await _fetch_forced_memory_items(
        db,
        forced_ids,
        project_id=project_id,
        include_global=True,
        include_mandates=True,
        include_guardrails=True,
        include_references=True,
        exclude_tags=[],
        exclude_memory_uuids=[],
        consumer_surface="agent_runtime",
        consumer_profile=consumer_profile,
        consumer_agent_slug=None,
        consumer_tags=[],
    )
    for item in forced_items:
        if item.uuid in loaded_ids or item.uuid in excluded_ids:
            continue
        _append_forced_memory_item(context, item)
        loaded_ids.add(item.uuid)

    # Re-plan all render tiers now that forced includes/excludes have changed
    # the selected set, then let explicit UI render overrides win last.
    plan_context_render_tiers(
        context.mandates,
        context.guardrails,
        context.reference_index,
        context.reference,
        query,
        consumer_profile=consumer_profile,
    )

    items_by_id = {
        item.uuid: item
        for item in (
            list(context.mandates)
            + list(context.guardrails)
            + list(context.reference_index)
            + list(context.reference)
        )
        if item.uuid
    }
    position_by_id: dict[str, int] = {}
    for override in overrides:
        if override.source_id in excluded_ids:
            continue
        if override.mode in {"include", "order"}:
            position_by_id[override.source_id] = override.position
        if override.tier_override:
            target = items_by_id.get(override.source_id)
            if target is not None:
                apply_render_tier(target, override.tier_override, "user_override")

    _sort_context_by_override_position(context, position_by_id)
    _refresh_runtime_context_totals(context)
    context.debug_info["runtime_context_overrides_applied"] = True
    context.debug_info["runtime_context_override_count"] = len(overrides)
    return context


def _drop_memory_ids(context: ProgressiveContext, memory_ids: set[str]) -> None:
    if not memory_ids:
        return
    context.mandates = [item for item in context.mandates if item.uuid not in memory_ids]
    context.guardrails = [item for item in context.guardrails if item.uuid not in memory_ids]
    context.reference_index = [
        item for item in context.reference_index if item.uuid not in memory_ids
    ]
    context.reference = [item for item in context.reference if item.uuid not in memory_ids]


def _append_forced_memory_item(
    context: ProgressiveContext,
    item: MemorySearchResult,
) -> None:
    if item.category == MemoryCategory.MANDATE:
        context.mandates.append(item)
        return
    if item.category == MemoryCategory.GUARDRAIL:
        context.guardrails.append(item)
        return
    if getattr(item.context_kind, "value", item.context_kind) == "capability":
        context.reference_index.append(item)
        return
    context.reference.append(item)


def _sort_context_by_override_position(
    context: ProgressiveContext,
    position_by_id: dict[str, int],
) -> None:
    if not position_by_id:
        return

    def sort_items(items: list[MemorySearchResult]) -> list[MemorySearchResult]:
        return [
            item
            for _index, item in sorted(
                enumerate(items),
                key=lambda pair: (
                    position_by_id.get(pair[1].uuid, 10_000 + pair[0]),
                    pair[0],
                ),
            )
        ]

    context.mandates = sort_items(context.mandates)
    context.guardrails = sort_items(context.guardrails)
    context.reference_index = sort_items(context.reference_index)
    context.reference = sort_items(context.reference)


def _refresh_runtime_context_totals(context: ProgressiveContext) -> None:
    budget = context.budget_usage or BudgetUsage()
    budget.mandates_total = len(context.mandates)
    budget.guardrails_total = len(context.guardrails)
    budget.reference_total = len(context.reference_index) + len(context.reference)
    budget.mandates_tokens = sum(
        count_tokens(get_rendered_content(item)) for item in context.mandates
    )
    budget.guardrails_tokens = sum(
        count_tokens(get_rendered_content(item)) for item in context.guardrails
    )
    budget.reference_tokens = sum(
        count_tokens(get_rendered_content(item))
        for item in [*context.reference_index, *context.reference]
    )
    context.budget_usage = budget
    context.total_tokens = budget.total_tokens
    context.debug_info.update(
        {
            "mandates_count": len(context.mandates),
            "guardrails_count": len(context.guardrails),
            "reference_count": len(context.reference_index) + len(context.reference),
            "reference_index_count": len(context.reference_index),
            "total_tokens": context.total_tokens,
        }
    )


def _render_blocks(blocks: list[RuntimeContextBlockResponse]) -> str:
    chunks: list[str] = []
    memory_lines: list[str] = []

    def flush_memory_lines() -> None:
        if memory_lines:
            chunks.append("## Runtime Memory\n" + "\n".join(memory_lines))
            memory_lines.clear()

    for block in blocks:
        if block.mode == "exclude":
            continue
        if block.source_type == "prompt":
            flush_memory_lines()
            chunks.append(f"## {block.title}\n{block.content.strip()}")
            continue
        label = {"mandate": "M", "guardrail": "G"}.get(block.tier or "", "R")
        memory_lines.append(
            f"- [{label}:{block.source_id[:8]}] {block.content.strip()}"
        )
    flush_memory_lines()
    return "\n\n".join(chunk for chunk in chunks if chunk.strip())


class RuntimeContextProfilePolicyResponse(BaseModel):
    consumer_profile: str
    mandate_limit: int | None
    guardrail_limit: int | None
    reference_limit: int | None


class RuntimeContextProfilePolicyUpdate(BaseModel):
    """All limit fields are nullable; null = uncapped, integer = explicit cap."""

    mandate_limit: int | None = None
    guardrail_limit: int | None = None
    reference_limit: int | None = None


def _python_fallback_policy(consumer_profile: str) -> RuntimeContextProfilePolicyResponse:
    profile = resolve_consumer_profile(consumer_profile)
    mandate, guardrail = _PROFILE_POLICY_LIMITS.get(profile, (0, 0))
    return RuntimeContextProfilePolicyResponse(
        consumer_profile=profile.value,
        mandate_limit=mandate or None,
        guardrail_limit=guardrail or None,
        reference_limit=None,
    )


async def get_runtime_context_profile_policy(
    db: AsyncSession,
    *,
    consumer_profile: str,
) -> RuntimeContextProfilePolicyResponse:
    profile = resolve_consumer_profile(consumer_profile)
    row = await db.get(RuntimeContextProfilePolicy, profile.value)
    if row is None:
        return _python_fallback_policy(consumer_profile)
    return RuntimeContextProfilePolicyResponse(
        consumer_profile=row.consumer_profile,
        mandate_limit=row.mandate_limit,
        guardrail_limit=row.guardrail_limit,
        reference_limit=row.reference_limit,
    )


async def upsert_runtime_context_profile_policy(
    db: AsyncSession,
    *,
    consumer_profile: str,
    payload: RuntimeContextProfilePolicyUpdate,
) -> RuntimeContextProfilePolicyResponse:
    profile = resolve_consumer_profile(consumer_profile)
    row = await db.get(RuntimeContextProfilePolicy, profile.value)
    if row is None:
        row = RuntimeContextProfilePolicy(consumer_profile=profile.value)
        db.add(row)
    row.mandate_limit = payload.mandate_limit
    row.guardrail_limit = payload.guardrail_limit
    row.reference_limit = payload.reference_limit
    await db.commit()
    await db.refresh(row)
    invalidate_policy_cache()
    return RuntimeContextProfilePolicyResponse(
        consumer_profile=row.consumer_profile,
        mandate_limit=row.mandate_limit,
        guardrail_limit=row.guardrail_limit,
        reference_limit=row.reference_limit,
    )
