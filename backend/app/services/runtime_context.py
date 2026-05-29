"""Runtime context profile rendering for external agentic CLIs."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
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
from app.services.memory.budget import count_tokens
from app.services.memory.context_builder import build_progressive_context
from app.services.memory.context_builder_tiers import (
    apply_render_tier,
    get_rendered_content,
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
from app.services.memory.service import MemoryScope, MemorySearchResult
from app.services.memory.settings import get_memory_settings
from app.services.memory.st_usage_memory import decay_score_by_surface
from app.services.memory.tool_capability_context import format_tool_capability_context
from app.services.project_permission_service import get_visible_tools_for_project

RuntimeSourceType = Literal["prompt", "memory"]
RuntimeOverrideMode = Literal["include", "exclude", "order"]
RuntimeBlockSource = Literal["auto", "pinned"]
RuntimeTierOverride = Literal["L0", "L1", "L2"]


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
    tool_capabilities: str = ""
    # Terse U-shaped footer restating the top mandates. Rendered last so the
    # highest-priority rules bookend the payload (start + end). total_tokens
    # already accounts for it.
    non_negotiables: str = ""


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
    candidates.extend(await _build_prompt_blocks(db, overrides, override_by_key, excluded_keys))
    candidates.extend(await _build_memory_blocks(
        db,
        consumer_profile=consumer_profile,
        project_id=project_id,
        query=query,
        task_type=task_type,
        phase=phase,
        include_global=include_global,
        overrides=overrides,
        override_by_key=override_by_key,
        excluded=excluded_keys,
    ))
    candidates.sort(key=lambda block: (block.position, _source_sort(block.source_type), block.source_id))

    rendered_blocks = [block for block in candidates if block.mode != "exclude"]
    excluded_blocks = [block for block in candidates if block.mode == "exclude"]
    rendered = _render_blocks(rendered_blocks)

    project_index_block, tool_capability_block = await _compute_auxiliary_blocks(
        consumer_profile=consumer_profile,
        project_id=project_id,
        task_type=task_type,
    )
    non_negotiables = _render_non_negotiables(rendered_blocks)
    # Order: project index -> mandates/guardrails -> tool capabilities ->
    # non-negotiables footer. Mandates render before the (larger) tool catalog
    # so the rules the model must follow are never the first thing truncated,
    # and the footer restates the top few (U-shaped attention).
    full_rendered = "\n".join(
        chunk
        for chunk in (project_index_block, rendered, tool_capability_block, non_negotiables)
        if chunk
    )

    settings = await get_memory_settings(db)
    return RuntimeContextPreviewResponse(
        consumer_profile=consumer_profile,
        project_id=project_id,
        query=query,
        total_tokens=count_tokens(full_rendered),
        budget_tokens=settings.total_budget,
        budget_enabled=settings.budget_enabled,
        rendered=rendered,
        blocks=rendered_blocks,
        excluded=excluded_blocks,
        overrides=[_override_response(row) for row in override_rows],
        project_index=project_index_block,
        tool_capabilities=tool_capability_block,
        non_negotiables=non_negotiables,
    )


async def _compute_auxiliary_blocks(
    *,
    consumer_profile: str,
    project_id: str | None,
    task_type: str | None,
) -> tuple[str, str]:
    """Mirror context_injector_ops.run_injection_operation auxiliary blocks.

    The frontend preview must match what an agent actually receives at
    session start, which prepends project_index + tool_capabilities to the
    rendered prompts/memories.
    """
    project_index_block = format_project_index_context(
        project_id, consumer_profile=consumer_profile, task_type=task_type
    )
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
    tool_capability_block = format_tool_capability_context(
        consumer_profile=consumer_profile,
        task_type=task_type,
        project_id=project_id,
        bash_available=bash_available,
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
) -> list[RuntimeContextBlockResponse]:
    pinned_slugs = {
        item.source_id
        for item in overrides
        if item.enabled and item.source_type == "prompt" and item.mode == "include"
    }
    # Boot-eligible prompts auto-inject; pinned-via-override prompts also appear.
    stmt = select(Prompt).where(Prompt.enabled.is_(True)).where(
        or_(Prompt.boot_eligible.is_(True), Prompt.slug.in_(list(pinned_slugs)))
        if pinned_slugs
        else Prompt.boot_eligible.is_(True)
    )
    result = await db.execute(stmt)
    prompts = list(result.scalars().all())

    blocks: list[RuntimeContextBlockResponse] = []
    for prompt in prompts:
        key = ("prompt", prompt.slug)
        ovr = override_by_key.get(key)
        is_pinned = bool(ovr and ovr.mode == "include")
        is_excluded = key in excluded
        position = ovr.position if ovr else _default_prompt_position(prompt)
        tags = []
        if prompt.prompt_type and prompt.prompt_type != "standard":
            tags.append(prompt.prompt_type)
        scope = "global" if prompt.is_global else "agent"
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
                auto_reason=None if is_pinned else "boot_eligible",
                mode="exclude" if is_excluded else ("include" if is_pinned else "order"),
                position=position,
                scope=scope,
                scope_id=None,
                tags=tags,
            )
        )
    return blocks


async def _build_memory_blocks(
    db: AsyncSession,
    *,
    consumer_profile: str,
    project_id: str | None,
    query: str,
    task_type: str | None,
    phase: str | None,
    include_global: bool,
    overrides: list[_ResolvedOverride],
    override_by_key: dict[tuple[str, str], _ResolvedOverride],
    excluded: set[tuple[str, str]],
) -> list[RuntimeContextBlockResponse]:
    scope = MemoryScope.PROJECT if project_id else MemoryScope.GLOBAL
    context = await build_progressive_context(
        query=query,
        scope=scope,
        scope_id=project_id,
        include_global=include_global,
        task_type=task_type,
        phase=phase,
        consumer_profile=consumer_profile,
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
    forced_items = await _fetch_forced_memory_items(db, forced_ids)
    forced_uuids = {item.uuid for item in forced_items}
    auto_items.extend((item, _tier_for_memory(item), 0) for item in forced_items)

    # Apply per-profile/per-project tier overrides before reading rendered content.
    for item, _block_tier, _index in auto_items:
        ovr = override_by_key.get(("memory", item.uuid))
        if ovr and ovr.tier_override:
            apply_render_tier(item, ovr.tier_override, "user_override")

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
            )
        )
    return blocks


async def _fetch_forced_memory_items(db: AsyncSession, source_ids: list[str]) -> list[MemorySearchResult]:
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
        if item:
            items.append(item)
    return items


def _tier_for_memory(item: MemorySearchResult) -> str:
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
    # Prompts render before memories — offset well below mandate base (1000).
    # Sort by id so insertion order is deterministic; multiply to leave room
    # for manual reordering between adjacent prompts.
    return 100 + (prompt.id or 0) * 5


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


# How many top mandates the non-negotiables footer restates. Terse by design —
# this is cheap reinforcement, not a second full copy of the mandate union.
_NON_NEGOTIABLE_LIMIT = 10


def _render_non_negotiables(
    blocks: list[RuntimeContextBlockResponse],
    limit: int = _NON_NEGOTIABLE_LIMIT,
) -> str:
    """Restate the top mandates as a terse footer (U-shaped attention).

    `blocks` arrive pre-sorted by position, so the first mandates are the
    highest-priority ones. Emits citation + one-line summary only.
    """
    lines: list[str] = []
    for block in blocks:
        if block.source_type != "memory" or block.tier != "mandate":
            continue
        summary = (block.title or "").strip()
        if not summary:
            continue
        lines.append(f"- [M:{block.source_id[:8]}] {summary}")
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    return "## Non-negotiables (top mandates restated)\n" + "\n".join(lines)


def _render_blocks(blocks: list[RuntimeContextBlockResponse]) -> str:
    chunks: list[str] = []
    memory_lines: list[str] = []
    for block in blocks:
        if block.mode == "exclude":
            continue
        if block.source_type == "prompt":
            chunks.append(f"## {block.title}\n{block.content.strip()}")
            continue
        label = {"mandate": "M", "guardrail": "G"}.get(block.tier or "", "R")
        memory_lines.append(
            f"- [{label}:{block.source_id[:8]}] {block.content.strip()}"
        )
    if memory_lines:
        chunks.append("## Runtime Memory\n" + "\n".join(memory_lines))
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
