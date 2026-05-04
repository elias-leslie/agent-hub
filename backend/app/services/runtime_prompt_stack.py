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
    GLOBAL_GUARDRAIL_PROMPT_TYPE,
    GLOBAL_MANDATE_PROMPT_TYPE,
)
from app.services.prompt_service import (
    get_agent_prompts,
    get_all_prompts,
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
    include_global_prompts: bool = True,
    include_mandates: bool = True,
    include_guardrails: bool = True,
    include_persona_context: bool = True,
) -> list[RuntimePromptSection]:
    """Collect the runtime system-prompt sections in injection order."""
    sections: list[RuntimePromptSection] = []

    if include_global_prompts:
        global_prompts = await get_all_prompts(db, is_global=True)
        for prompt in global_prompts:
            if not prompt.enabled:
                continue
            if agent.slug and prompt.exclude_agents and agent.slug in prompt.exclude_agents:
                continue
            if prompt.prompt_type == GLOBAL_MANDATE_PROMPT_TYPE and not include_mandates:
                continue
            if prompt.prompt_type == GLOBAL_GUARDRAIL_PROMPT_TYPE and not include_guardrails:
                continue
            sections.append(
                RuntimePromptSection(
                    label=prompt.name,
                    source_kind="global_prompt",
                    source_id=prompt.slug,
                    content=prompt.content,
                    updated_at=prompt.updated_at,
                )
            )

    assignments = await get_agent_prompts(
        db,
        agent.id,
        include_roles=include_roles,
        exclude_roles=get_runtime_excluded_prompt_roles(
            agent_slug=getattr(agent, "slug", None),
            task_type=task_type,
        ),
    )
    enabled_assignments = [assignment for assignment in assignments if assignment.prompt.enabled]
    has_owned_system_prompt = any(
        assignment.prompt.prompt_type == AGENT_SYSTEM_PROMPT_TYPE
        for assignment in enabled_assignments
    )
    if not has_owned_system_prompt:
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
