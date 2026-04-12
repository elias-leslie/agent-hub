"""Config snapshot capture and fingerprinting for agent benchmarks."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import Agent, Memory, MemoryRevision, Persona, Prompt
from app.services.agent_crud import get_agent_by_slug
from app.services.agent_dto import AgentDTO
from app.services.memory.context_builder_settings import (
    default_agent_memory_config,
    normalize_memory_config,
    resolve_memory_consumer_profile,
)
from app.services.memory.governance import collect_memory_governance_snapshot
from app.services.memory.project_index_context import format_project_index_context
from app.services.memory.tool_capability_context import format_tool_capability_context
from app.services.prompt_catalog import (
    COMPLETION_REVIEW_PROMPT_SLUG,
    COMPLETION_REVIEW_RULES_PROMPT_SLUG,
    PERSONA_FOCUS_HARNESS_PROMPT_SLUG,
    PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG,
    PERSONA_HEARTBEAT_PROMPT_SLUG,
    PERSONA_WAKE_GUIDANCE_PROMPT_SLUG,
)
from app.services.runtime_prompt_stack import collect_runtime_prompt_sections


def heartbeat_prompt_descriptor(config_snapshot: dict[str, Any]) -> str | None:
    heartbeat = config_snapshot.get("heartbeat_prompt")
    if not isinstance(heartbeat, dict):
        return None
    updated_at = heartbeat.get("updated_at")
    content_hash = heartbeat.get("content_hash")
    if not updated_at or not content_hash:
        return None
    return f"{updated_at}:{content_hash}"


def memory_state_descriptor(config_snapshot: dict[str, Any]) -> str | None:
    memory_state = config_snapshot.get("memory_state")
    if not isinstance(memory_state, dict):
        return None
    latest_revision_id = memory_state.get("latest_revision_id")
    latest_revision_at = memory_state.get("latest_revision_at")
    if not latest_revision_id or not latest_revision_at:
        return None
    descriptor = f"{latest_revision_at}:{latest_revision_id}"
    variant_override = memory_state.get("variant_override")
    if variant_override:
        descriptor = f"{descriptor}:{variant_override}"
    return descriptor


def normalize_config_snapshot_for_fingerprint(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: normalize_config_snapshot_for_fingerprint(item)
            for key, item in value.items()
            if key != "captured_at"
        }
    if isinstance(value, list):
        return [normalize_config_snapshot_for_fingerprint(item) for item in value]
    return value


def run_config_fingerprint(run: object) -> str:
    payload = {
        "config_snapshot": normalize_config_snapshot_for_fingerprint(
            dict(getattr(run, "config_snapshot", None) or {})
        ),
        "models": list(getattr(run, "models", []) or []),
        "case_ids": list(getattr(run, "case_ids", []) or []),
        "runs_per_case": int(getattr(run, "runs_per_case", 1) or 1),
        "use_memory": bool(getattr(run, "use_memory", False)),
        "run_kind": str(getattr(run, "run_kind", "") or ""),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:10]


def _task_prompt_slugs(task_type: str | None) -> list[str]:
    if task_type == "heartbeat":
        return [
            PERSONA_HEARTBEAT_PROMPT_SLUG,
            PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG,
            PERSONA_FOCUS_HARNESS_PROMPT_SLUG,
        ]
    if task_type == "wake":
        return [
            PERSONA_WAKE_GUIDANCE_PROMPT_SLUG,
            PERSONA_FOCUS_HARNESS_PROMPT_SLUG,
        ]
    if task_type == "review":
        return [
            COMPLETION_REVIEW_PROMPT_SLUG,
            COMPLETION_REVIEW_RULES_PROMPT_SLUG,
        ]
    return []


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _effective_memory_config_for_agent(agent: Agent) -> dict[str, Any]:
    return normalize_memory_config(getattr(agent, "memory_config", None)) or default_agent_memory_config()


def _descriptor_for_generated_channel(channel: str, content: str) -> str | None:
    if not content:
        return None
    return f"generated:{channel}:{_content_hash(content)}"


def _capture_generated_context(
    agent: Agent,
    *,
    task_type: str | None,
    project_id: str | None = None,
) -> dict[str, Any]:
    memory_config = _effective_memory_config_for_agent(agent)
    consumer_profile = resolve_memory_consumer_profile(memory_config, surface="runtime")
    descriptors: list[str] = []

    project_index_enabled = bool(memory_config.get("project_index_enabled", True))
    project_index_text = (
        format_project_index_context(
            project_id,
            consumer_profile=consumer_profile,
            task_type=task_type,
        )
        if project_index_enabled
        else ""
    )
    if descriptor := _descriptor_for_generated_channel("project_index", project_index_text):
        descriptors.append(descriptor)

    tool_capabilities_enabled = bool(memory_config.get("tool_capabilities_enabled", True))
    tool_capability_text = (
        format_tool_capability_context(
            consumer_profile=consumer_profile,
            task_type=task_type,
            project_id=project_id,
        )
        if tool_capabilities_enabled
        else ""
    )
    if descriptor := _descriptor_for_generated_channel("tool_capabilities", tool_capability_text):
        descriptors.append(descriptor)

    return {
        "memory_config": memory_config,
        "consumer_profile": consumer_profile,
        "descriptors": descriptors,
        "project_index": {
            "enabled": project_index_enabled,
            "content_hash": _content_hash(project_index_text) if project_index_text else None,
            "content_length": len(project_index_text),
        },
        "tool_capabilities": {
            "enabled": tool_capabilities_enabled,
            "content_hash": _content_hash(tool_capability_text) if tool_capability_text else None,
            "content_length": len(tool_capability_text),
        },
    }


async def _capture_persona_snapshot(db: AsyncSession, agent: Agent) -> dict[str, Any]:
    persona = await db.scalar(select(Persona).where(Persona.agent_id == agent.id))
    snapshot: dict[str, Any] = {}

    if persona is not None:
        from app.services.persona_document_prompt_service import (
            get_persona_personality_document,
            get_persona_user_context_document,
        )

        personality_text = await get_persona_personality_document(db) or ""
        user_context_text = await get_persona_user_context_document(db) or ""
        snapshot["persona_documents"] = {
            "personality": {
                "content_hash": _content_hash(personality_text),
                "content_length": len(personality_text),
            },
            "user_context": {
                "content_hash": _content_hash(user_context_text),
                "content_length": len(user_context_text),
            },
            "user_profile": {
                "content_hash": _content_hash(
                    json.dumps(persona.user_profile or {}, sort_keys=True)
                ),
                "field_count": len(persona.user_profile or {}),
            },
            "onboarding_phase": persona.onboarding_phase,
        }

    prompt = await db.scalar(
        select(Prompt).where(Prompt.slug == PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG)
    )
    if prompt is not None:
        _text = prompt.content or ""
        snapshot["heartbeat_prompt"] = {
            "slug": prompt.slug,
            "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None,
            "content_hash": _content_hash(_text),
            "content_length": len(_text),
        }

    reviewer_agent = await db.scalar(select(Agent).where(Agent.slug == "supervisor"))
    if reviewer_agent is not None:
        snapshot["completion_reviewer"] = {
            "agent_slug": reviewer_agent.slug,
            "agent_version": reviewer_agent.version,
            "primary_model_id": reviewer_agent.primary_model_id,
            "fallback_models": list(reviewer_agent.fallback_models or []),
            "escalation_model_id": reviewer_agent.escalation_model_id,
            "thinking_level": reviewer_agent.thinking_level,
            "temperature": reviewer_agent.temperature,
        }
    return snapshot


async def _capture_prompt_stack(
    db: AsyncSession, agent: Agent, task_type: str | None,
) -> dict[str, Any]:
    prompt_sections = await collect_runtime_prompt_sections(db, agent, task_type=task_type)
    stack: dict[str, Any] = {
        "task_type": task_type,
        "system_sections": [section.to_snapshot_dict() for section in prompt_sections],
        "descriptors": [
            f"{section.source_kind}:{section.source_id}:{section.content_hash}"
            for section in prompt_sections
        ],
    }

    task_prompt_sources: list[dict[str, Any]] = []
    for prompt_slug in _task_prompt_slugs(task_type):
        prompt = await db.scalar(select(Prompt).where(Prompt.slug == prompt_slug))
        if prompt is not None:
            _text = prompt.content or ""
            task_prompt_sources.append({
                "slug": prompt.slug,
                "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None,
                "content_hash": _content_hash(_text),
                "content_length": len(_text),
            })
    if task_prompt_sources:
        stack["task_prompt_sources"] = task_prompt_sources
    return stack


async def _capture_preview_summary(
    db: AsyncSession,
    agent: Agent,
    *,
    task_type: str | None,
    project_id: str | None,
) -> dict[str, Any]:
    """Capture a compact preview-equivalent token summary for benchmark runs."""
    if not task_type:
        return {}

    from app.api.helpers.agent_preview import build_agent_preview

    preview = await build_agent_preview(
        db,
        AgentDTO.from_model(agent),
        task_type=task_type,
        project_id=project_id,
    )
    sections = preview.get("sections")
    if not isinstance(sections, list):
        return {}

    compact_sections: list[dict[str, Any]] = []
    by_source_kind: dict[str, int] = {}
    total_estimated_tokens = 0
    for section in sections:
        if not isinstance(section, dict):
            continue
        estimated_tokens = int(section.get("estimated_tokens") or 0)
        source_kind = str(section.get("source_kind") or "unknown")
        compact_sections.append(
            {
                "label": str(section.get("label") or source_kind),
                "source_kind": source_kind,
                "estimated_tokens": estimated_tokens,
                "chars": int(section.get("chars") or 0),
            }
        )
        by_source_kind[source_kind] = by_source_kind.get(source_kind, 0) + estimated_tokens
        total_estimated_tokens += estimated_tokens

    return {
        "task_type": task_type,
        "total_estimated_tokens": total_estimated_tokens,
        "sections": compact_sections,
        "by_source_kind": by_source_kind,
    }


async def _capture_memory_state(
    db: AsyncSession,
    *,
    memory_variant_override: str | None = None,
) -> dict[str, Any]:
    latest_memory_revision = await db.scalar(
        select(MemoryRevision).order_by(MemoryRevision.created_at.desc())
    )
    active_memory_count = await db.scalar(
        select(func.count()).select_from(Memory).where(Memory.status == "active")
    )
    snapshot = {
        "latest_revision_id": latest_memory_revision.id if latest_memory_revision else None,
        "latest_revision_at": (
            latest_memory_revision.created_at.isoformat()
            if latest_memory_revision and latest_memory_revision.created_at
            else None
        ),
        "latest_memory_uuid": latest_memory_revision.memory_uuid if latest_memory_revision else None,
        "active_count": int(active_memory_count or 0),
        "governance": await collect_memory_governance_snapshot(db),
    }
    if memory_variant_override:
        snapshot["variant_override"] = memory_variant_override
    return snapshot


async def capture_benchmark_config_snapshot(
    agent_slug: str,
    *,
    task_type: str | None = None,
    memory_variant_override: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Capture the live agent/model/prompt state for a benchmark run."""
    async with async_session() as db:
        agent = await get_agent_by_slug(db, agent_slug, active_only=True)
        if agent is None:
            return {}

        snapshot: dict[str, Any] = {
            "agent_version": agent.version,
            "primary_model_id": agent.primary_model_id,
            "fallback_models": list(agent.fallback_models or []),
            "escalation_model_id": agent.escalation_model_id,
            "thinking_level": agent.thinking_level,
            "temperature": agent.temperature,
            "captured_at": datetime.now(UTC).isoformat(),
        }

        snapshot["prompt_stack"] = await _capture_prompt_stack(db, agent, task_type)
        snapshot["preview_summary"] = await _capture_preview_summary(
            db,
            agent,
            task_type=task_type,
            project_id=project_id,
        )
        snapshot["generated_context"] = _capture_generated_context(
            agent,
            task_type=task_type,
            project_id=project_id,
        )
        snapshot["memory_state"] = await _capture_memory_state(
            db,
            memory_variant_override=memory_variant_override,
        )

        if agent_slug == "persona":
            snapshot.update(await _capture_persona_snapshot(db, agent))

        return snapshot
