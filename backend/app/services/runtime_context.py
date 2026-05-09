"""Runtime context profile rendering for external agentic CLIs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_unified import Memory
from app.models.prompt import Prompt
from app.models.runtime_context import RuntimeContextOverride
from app.services.memory.budget import count_tokens
from app.services.memory.context_builder import build_progressive_context
from app.services.memory.context_builder_tiers import get_rendered_content
from app.services.memory.context_injector_blocks_helpers import episode_to_result
from app.services.memory.repository import MemoryRepository
from app.services.memory.service import MemoryScope, MemorySearchResult

RuntimeSourceType = Literal["prompt", "memory"]
RuntimeOverrideMode = Literal["include", "exclude", "order"]

KNOWN_RUNTIME_PROFILES = (
    "codex_startup",
    "claude_session_start",
    "gemini_startup",
)


class RuntimeContextOverridePayload(BaseModel):
    source_type: RuntimeSourceType
    source_id: str
    mode: RuntimeOverrideMode = "include"
    position: int = Field(50, ge=1, le=9999)
    enabled: bool = True
    note: str | None = None


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
    mode: RuntimeOverrideMode
    position: int
    tier: str | None = None


class RuntimeContextPreviewResponse(BaseModel):
    consumer_profile: str
    project_id: str | None
    query: str
    total_tokens: int
    rendered: str
    blocks: list[RuntimeContextBlockResponse]
    overrides: list[RuntimeContextOverrideResponse]


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
    return [_override_response(row) for row in rows]


async def replace_runtime_context_overrides(
    db: AsyncSession,
    *,
    consumer_profile: str,
    project_id: str | None,
    overrides: list[RuntimeContextOverridePayload],
) -> list[RuntimeContextOverrideResponse]:
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
    overrides = _resolve_overrides(override_rows)
    override_by_key = {
        (item.source_type, item.source_id): item
        for item in overrides
        if item.enabled
    }
    excluded = {
        (item.source_type, item.source_id)
        for item in overrides
        if item.enabled and item.mode == "exclude"
    }

    blocks: list[RuntimeContextBlockResponse] = []
    blocks.extend(await _build_prompt_blocks(db, overrides, excluded))
    blocks.extend(await _build_memory_blocks(
        db,
        consumer_profile=consumer_profile,
        project_id=project_id,
        query=query,
        task_type=task_type,
        phase=phase,
        include_global=include_global,
        overrides=overrides,
        override_by_key=override_by_key,
        excluded=excluded,
    ))
    blocks.sort(key=lambda block: (block.position, _source_sort(block.source_type), block.source_id))
    rendered = _render_blocks(blocks)
    return RuntimeContextPreviewResponse(
        consumer_profile=consumer_profile,
        project_id=project_id,
        query=query,
        total_tokens=count_tokens(rendered),
        rendered=rendered,
        blocks=blocks,
        overrides=[_override_response(row) for row in override_rows],
    )


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
        )
    return list(resolved.values())


async def _build_prompt_blocks(
    db: AsyncSession,
    overrides: list[_ResolvedOverride],
    excluded: set[tuple[str, str]],
) -> list[RuntimeContextBlockResponse]:
    prompt_overrides = [
        item
        for item in overrides
        if item.enabled and item.source_type == "prompt" and item.mode == "include"
    ]
    if not prompt_overrides:
        return []
    slugs = [item.source_id for item in prompt_overrides]
    result = await db.execute(select(Prompt).where(Prompt.slug.in_(slugs), Prompt.enabled.is_(True)))
    prompts = {prompt.slug: prompt for prompt in result.scalars().all()}
    blocks: list[RuntimeContextBlockResponse] = []
    for item in prompt_overrides:
        if ("prompt", item.source_id) in excluded:
            continue
        prompt = prompts.get(item.source_id)
        if prompt is None:
            continue
        blocks.append(
            RuntimeContextBlockResponse(
                id=f"prompt:{prompt.slug}",
                source_type="prompt",
                source_id=prompt.slug,
                title=prompt.name,
                content=prompt.content,
                token_count=count_tokens(prompt.content),
                origin="override",
                mode="include",
                position=item.position,
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
    auto_items.extend((item, _tier_for_memory(item), 0) for item in forced_items)

    blocks: list[RuntimeContextBlockResponse] = []
    for item, tier, index in auto_items:
        if ("memory", item.uuid) in excluded:
            continue
        override = override_by_key.get(("memory", item.uuid))
        content = get_rendered_content(item)
        position = override.position if override else _default_memory_position(tier, item, index)
        blocks.append(
            RuntimeContextBlockResponse(
                id=f"memory:{item.uuid}",
                source_type="memory",
                source_id=item.uuid,
                title=item.summary or item.content.splitlines()[0][:80],
                content=content,
                token_count=count_tokens(content),
                origin="override" if override and override.mode == "include" else "auto",
                mode=(override.mode if override else "order"),
                position=position,
                tier=tier,
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


def _source_sort(source_type: str) -> int:
    return 0 if source_type == "prompt" else 1


def _render_blocks(blocks: list[RuntimeContextBlockResponse]) -> str:
    chunks: list[str] = []
    memory_lines: list[str] = []
    for block in blocks:
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
