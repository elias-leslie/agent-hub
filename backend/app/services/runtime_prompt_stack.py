"""Helpers for inspecting the assembled runtime prompt stack."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.owned_prompt_service import (
    AGENT_SYSTEM_PROMPT_TYPE,
    get_owned_prompt,
)
from app.services.prompt_service import (
    get_agent_prompts,
    get_runtime_excluded_prompt_roles,
)
from app.services.token_counter import count_tokens


@dataclass(frozen=True)
class RuntimePromptSection:
    label: str
    source_kind: str
    source_id: str
    content: str
    placement: str = "system"
    role: str | None = None
    priority: int | None = None
    updated_at: datetime | None = None
    duplicate_of: str | None = None

    @property
    def normalized_content(self) -> str:
        return normalize_runtime_prompt_content(self.content)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:8]

    @property
    def chars(self) -> int:
        return len(self.content)

    @property
    def estimated_tokens(self) -> int:
        return count_tokens(self.content) if self.content else 0

    def to_preview_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "placement": self.placement,
            "role": self.role,
            "priority": self.priority,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "content_hash": self.content_hash,
            "chars": self.chars,
            "estimated_tokens": self.estimated_tokens,
            "duplicate_of": self.duplicate_of,
            "content": self.content,
        }

    def to_snapshot_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "placement": self.placement,
            "role": self.role,
            "priority": self.priority,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "content_hash": self.content_hash,
            "chars": self.chars,
            "estimated_tokens": self.estimated_tokens,
            "duplicate_of": self.duplicate_of,
        }


_NORMALIZED_WHITESPACE_RE = re.compile(r"\s+")


def normalize_runtime_prompt_content(content: str) -> str:
    stripped = content.strip()
    if not stripped:
        return ""
    return _NORMALIZED_WHITESPACE_RE.sub(" ", stripped)


def dedupe_runtime_prompt_sections(
    sections: list[RuntimePromptSection],
) -> tuple[list[RuntimePromptSection], list[RuntimePromptSection]]:
    """Drop exact duplicate prompt content while preserving first occurrence order."""
    deduped: list[RuntimePromptSection] = []
    removed: list[RuntimePromptSection] = []
    seen_hashes: dict[str, RuntimePromptSection] = {}

    for section in sections:
        content = section.content.strip()
        if not content:
            continue
        normalized = normalize_runtime_prompt_content(content)
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
        original = seen_hashes.get(content_hash)
        if original and original.normalized_content == normalized:
            removed.append(
                RuntimePromptSection(
                    label=section.label,
                    source_kind=section.source_kind,
                    source_id=section.source_id,
                    content=section.content,
                    placement=section.placement,
                    role=section.role,
                    priority=section.priority,
                    updated_at=section.updated_at,
                    duplicate_of=f"{original.source_kind}:{original.source_id}",
                )
            )
            continue
        seen_hashes[content_hash] = section
        deduped.append(section)

    return deduped, removed


async def collect_runtime_prompt_sections(
    db: AsyncSession,
    agent: Any,
    *,
    include_roles: list[str] | None = None,
    task_type: str | None = None,
    project_id: str | None = None,
    prompt_mode: str = "full",
    include_global_prompts: bool = True,
    include_mandates: bool = True,
    include_guardrails: bool = True,
    include_persona_context: bool = True,
    query: str = "startup context",
    consumer_profile: str = "agent_runtime",
    consumer_tags: list[str] | None = None,
) -> list[RuntimePromptSection]:
    """Collect the runtime system-prompt sections in injection order."""
    sections: list[RuntimePromptSection] = []

    if include_global_prompts:
        from app.services.runtime_context import (
            CanonicalContextDeliveryRequest,
            build_canonical_context_delivery,
        )

        delivery = await build_canonical_context_delivery(
            db,
            CanonicalContextDeliveryRequest(
                consumer_surface="agent_prompt_stack",
                consumer_profile=consumer_profile,
                agent_slug=getattr(agent, "slug", None),
                consumer_tags=consumer_tags or [],
                project_id=project_id,
                query=query,
                task_type=task_type,
                include_memories=False,
                include_mandates=include_mandates,
                include_guardrails=include_guardrails,
                include_project_index=False,
                include_tool_capabilities=False,
                include_continuity=False,
            ),
        )
        for block in delivery.blocks:
            if block.provenance.source_type != "prompt":
                continue
            sections.append(
                RuntimePromptSection(
                    label=block.title,
                    source_kind="global_prompt",
                    source_id=block.provenance.source_id,
                    content=block.content,
                )
            )
        if delivery.status != "ok":
            sections.append(
                RuntimePromptSection(
                    label="Canonical Context Failure",
                    source_kind="canonical_context_failure",
                    source_id=delivery.delivery_id,
                    content=delivery.rendered,
                )
            )

    assignments = await get_agent_prompts(
        db,
        agent.id,
        include_roles=include_roles,
        exclude_roles=get_runtime_excluded_prompt_roles(
            agent_slug=getattr(agent, "slug", None),
            prompt_mode=prompt_mode,
            task_type=task_type,
        ),
    )
    # Global prompt ownership is assembled once by canonical context. An old or
    # redundant AgentPrompt assignment must not duplicate that content in the
    # agent-specific layer.
    agent_specific_assignments = [
        assignment
        for assignment in assignments
        if not assignment.prompt.is_global
    ]
    enabled_assignments = [
        assignment
        for assignment in agent_specific_assignments
        if assignment.prompt.enabled
    ]
    has_owned_system_prompt = any(
        assignment.prompt.prompt_type == AGENT_SYSTEM_PROMPT_TYPE
        for assignment in agent_specific_assignments
    )
    system_role_in_scope = include_roles is None or "system" in include_roles
    unassigned_owned_system_prompt = None
    if not has_owned_system_prompt and system_role_in_scope:
        # Assignment drift must not revive the Agent compatibility mirror.
        # Read the canonical owned row directly when no assignment surfaced:
        # enabled rows still render, while disabled rows explicitly render
        # nothing. Only a truly absent/unmigrated row permits the mirror.
        unassigned_owned_system_prompt = await get_owned_prompt(
            db,
            agent_id=agent.id,
            prompt_type=AGENT_SYSTEM_PROMPT_TYPE,
        )

    if unassigned_owned_system_prompt is not None:
        prompt = unassigned_owned_system_prompt
        content = (prompt.content or "").strip()
        if prompt.enabled and content:
            sections.append(
                RuntimePromptSection(
                    label=prompt.name,
                    source_kind="agent_system_prompt",
                    source_id=prompt.slug,
                    content=content,
                    role="system",
                    priority=0,
                    updated_at=prompt.updated_at,
                )
            )
    elif not has_owned_system_prompt and system_role_in_scope:
        system_prompt = (getattr(agent, "system_prompt", None) or "").strip()
        if system_prompt:
            sections.append(
                RuntimePromptSection(
                    label=f"{getattr(agent, 'name', 'Agent')} System Prompt",
                    source_kind="agent_system_prompt",
                    source_id=getattr(agent, "slug", "agent"),
                    content=f"<agent_persona>\n{system_prompt}\n</agent_persona>",
                )
            )

    for assignment in enabled_assignments:
        prompt = assignment.prompt
        sections.append(
            RuntimePromptSection(
                label=prompt.name,
                source_kind=(
                    "agent_system_prompt"
                    if prompt.prompt_type == AGENT_SYSTEM_PROMPT_TYPE
                    else "agent_prompt"
                ),
                source_id=prompt.slug,
                content=prompt.content,
                role=assignment.role,
                priority=assignment.priority,
                updated_at=prompt.updated_at,
            )
        )

    if include_persona_context:
        from app.services.persona_service import get_persona_context_for_agent

        persona_context = await get_persona_context_for_agent(
            db,
            agent.id,
            task_type=task_type,
            mutate_phase=False,
        )
        if persona_context:
            sections.append(
                RuntimePromptSection(
                    label="Persona Context",
                    source_kind="persona_context",
                    source_id=agent.slug,
                    content=f"<persona_context>\n{persona_context}\n</persona_context>",
                )
            )

    if project_id:
        from app.services.agent_routing_utils import _build_project_permissions_block

        permissions = await _build_project_permissions_block(
            project_id, db, agent_slug=agent.slug,
        )
        if permissions:
            sections.append(
                RuntimePromptSection(
                    label="Project Permissions",
                    source_kind="project_permissions",
                    source_id=project_id,
                    content=permissions,
                )
            )

    deduped_sections, _ = dedupe_runtime_prompt_sections(sections)
    return deduped_sections


def join_runtime_prompt_sections(sections: list[RuntimePromptSection]) -> str:
    return "\n\n".join(section.content for section in sections if section.content)


__all__ = [
    "RuntimePromptSection",
    "collect_runtime_prompt_sections",
    "dedupe_runtime_prompt_sections",
    "join_runtime_prompt_sections",
    "normalize_runtime_prompt_content",
]
