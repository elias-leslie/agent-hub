"""Helpers for inspecting the assembled runtime prompt stack."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.prompt_service import get_agent_prompts, get_all_prompts
from app.services.token_counter import count_tokens


@dataclass(frozen=True)
class RuntimePromptSection:
    label: str
    source_kind: str
    source_id: str
    content: str
    role: str | None = None
    priority: int | None = None
    updated_at: datetime | None = None

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
            "role": self.role,
            "priority": self.priority,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "content_hash": self.content_hash,
            "chars": self.chars,
            "estimated_tokens": self.estimated_tokens,
            "content": self.content,
        }

    def to_snapshot_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "role": self.role,
            "priority": self.priority,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "content_hash": self.content_hash,
            "chars": self.chars,
            "estimated_tokens": self.estimated_tokens,
        }


async def collect_runtime_prompt_sections(
    db: AsyncSession,
    agent: Any,
    *,
    task_type: str | None = None,
    project_id: str | None = None,
) -> list[RuntimePromptSection]:
    """Collect the runtime system-prompt sections in injection order."""
    sections: list[RuntimePromptSection] = []

    global_prompts = await get_all_prompts(db, is_global=True)
    for prompt in global_prompts:
        if not prompt.enabled:
            continue
        if agent.slug and prompt.exclude_agents and agent.slug in prompt.exclude_agents:
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

    assignments = await get_agent_prompts(db, agent.id)
    for assignment in assignments:
        prompt = assignment.prompt
        if not prompt.enabled:
            continue
        sections.append(
            RuntimePromptSection(
                label=prompt.name,
                source_kind="agent_prompt",
                source_id=prompt.slug,
                content=prompt.content,
                role=assignment.role,
                priority=assignment.priority,
                updated_at=prompt.updated_at,
            )
        )

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

        permissions = await _build_project_permissions_block(project_id, db)
        if permissions:
            sections.append(
                RuntimePromptSection(
                    label="Project Permissions",
                    source_kind="project_permissions",
                    source_id=project_id,
                    content=permissions,
                )
            )

    return sections


def join_runtime_prompt_sections(sections: list[RuntimePromptSection]) -> str:
    return "\n\n".join(section.content for section in sections if section.content)


__all__ = [
    "RuntimePromptSection",
    "collect_runtime_prompt_sections",
    "join_runtime_prompt_sections",
]
