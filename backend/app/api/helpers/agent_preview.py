"""Agent preview helper functions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_dto import AgentDTO
from app.services.canonical_context_adapters import (
    canonical_context_contract,
    progressive_context_from_delivery,
)
from app.services.memory.context_builder_settings import (
    memory_injection_enabled,
    resolve_continuity_settings,
    resolve_excluded_memory_uuids,
    resolve_memory_config_includes,
    resolve_memory_consumer_profile,
    resolve_memory_tags,
    resolve_project_index_enabled,
    resolve_reference_index_enabled,
    resolve_runtime_prompt_includes,
    resolve_tool_capabilities_enabled,
)
from app.services.memory.context_injector import extract_query_from_messages
from app.services.memory.settings import get_memory_settings
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    build_canonical_context_delivery,
)
from app.services.runtime_prompt_stack import (
    RuntimePromptSection,
    collect_runtime_prompt_sections,
    join_runtime_prompt_sections,
)
from app.services.token_counter import count_tokens

_PREVIEW_PROMPT_WARN_TOKENS = 3_200
_PREVIEW_PROMPT_DANGER_TOKENS = 4_500
_PREVIEW_LOW_YIELD_SOURCE_KINDS = {"persona_context", "memory_context", "task_prompt"}
_PREVIEW_LOW_YIELD_SHARE_WARN = 0.45
_PREVIEW_SECTION_SHARE_WARN = 0.2


def _build_budget_telemetry(
    sections: list[RuntimePromptSection],
    dropped_sections: list[RuntimePromptSection],
) -> dict[str, Any]:
    total_tokens = sum(section.estimated_tokens for section in sections)
    low_yield_sections = [
        section for section in sections if section.source_kind in _PREVIEW_LOW_YIELD_SOURCE_KINDS
    ]
    low_yield_tokens = sum(section.estimated_tokens for section in low_yield_sections)
    top_sections = sorted(sections, key=lambda section: section.estimated_tokens, reverse=True)[:5]

    warnings: list[str] = []
    severity = "ok"
    if total_tokens >= _PREVIEW_PROMPT_DANGER_TOKENS:
        severity = "danger"
        warnings.append(
            f"Prompt budget danger: {total_tokens} tokens total; low-yield sections carry {low_yield_tokens}."
        )
    elif total_tokens >= _PREVIEW_PROMPT_WARN_TOKENS:
        severity = "warning"
        warnings.append(
            f"Prompt budget warning: {total_tokens} tokens total; low-yield sections carry {low_yield_tokens}."
        )
    if low_yield_tokens and total_tokens and low_yield_tokens / total_tokens >= _PREVIEW_LOW_YIELD_SHARE_WARN:
        warnings.append(
            f"Low-yield pressure high: persona/memory/task sections use {low_yield_tokens}/{total_tokens} tokens."
        )
    if dropped_sections:
        warnings.append(
            f"Dropped {len(dropped_sections)} exact-duplicate sections before preview assembly."
        )

    top_low_yield_sections = [
        section for section in top_sections if section.source_kind in _PREVIEW_LOW_YIELD_SOURCE_KINDS
    ]
    section_breakdown = [
        {
            "label": section.label,
            "source_kind": section.source_kind,
            "source_id": section.source_id,
            "estimated_tokens": section.estimated_tokens,
            "chars": section.chars,
            "share_of_total": round(section.estimated_tokens / total_tokens, 3) if total_tokens else 0.0,
            "duplicate_of": section.duplicate_of,
        }
        for section in sorted(sections, key=lambda section: section.estimated_tokens, reverse=True)
    ]
    for section in top_low_yield_sections:
        if total_tokens and section.estimated_tokens / total_tokens >= _PREVIEW_SECTION_SHARE_WARN:
            warnings.append(
                f"Low-yield hotspot: {section.label} uses {section.estimated_tokens}/{total_tokens} tokens."
            )
    return {
        "severity": severity,
        "total_estimated_tokens": total_tokens,
        "warn_threshold_tokens": _PREVIEW_PROMPT_WARN_TOKENS,
        "danger_threshold_tokens": _PREVIEW_PROMPT_DANGER_TOKENS,
        "low_yield_estimated_tokens": low_yield_tokens,
        "low_yield_section_count": len(low_yield_sections),
        "low_yield_share_of_total": round(low_yield_tokens / total_tokens, 3) if total_tokens else 0.0,
        "warning_count": len(warnings),
        "warnings": warnings,
        "top_sections": [
            {
                "label": section.label,
                "source_kind": section.source_kind,
                "source_id": section.source_id,
                "estimated_tokens": section.estimated_tokens,
                "chars": section.chars,
                "share_of_total": round(section.estimated_tokens / total_tokens, 3) if total_tokens else 0.0,
            }
            for section in top_sections
        ],
        "top_low_yield_sections": [
            {
                "label": section.label,
                "source_kind": section.source_kind,
                "source_id": section.source_id,
                "estimated_tokens": section.estimated_tokens,
                "chars": section.chars,
                "share_of_total": round(section.estimated_tokens / total_tokens, 3) if total_tokens else 0.0,
            }
            for section in top_low_yield_sections[:3]
        ],
        "section_breakdown": section_breakdown,
        "dropped_duplicates": [section.to_snapshot_dict() for section in dropped_sections],
    }



async def _build_task_prompt_preview(
    agent: AgentDTO,
    *,
    task_type: str | None,
    project_id: str | None,
    phase: str | None,
    prompt_input: str | None,
) -> str | None:
    if task_type in (None, "", "chat"):
        return None

    if task_type == "heartbeat":
        from app.routing.registry import get_provider_for_model
        from app.workflows._heartbeat_prompt import build_heartbeat_prompt
        from app.workflows._heartbeat_redis import get_model_review_status

        model_review_due, model_review_label = await get_model_review_status()
        provider = get_provider_for_model(agent.primary_model_id)
        return await build_heartbeat_prompt(
            model_review_due,
            model_review_label,
            target_project_id=project_id,
            provider=provider,
        )

    if task_type == "wake":
        from app.workflows.persona_wake import _build_wake_prompt

        return await _build_wake_prompt(prompt_input or "(preview placeholder task)")

    if task_type == "review":
        from app.workflows._completion_review import _build_review_prompt

        return await _build_review_prompt(
            completion_content=prompt_input or "HEARTBEAT_OK — Preview placeholder.",
            cleanup_status="(preview placeholder cleanup status)",
            workstream_inventory=phase or "(preview placeholder workstream inventory)",
        )

    return prompt_input


def _build_preview_memory_query(task_prompt: str | None, prompt_input: str | None) -> str:
    """Mirror runtime memory-query extraction from the latest user message."""
    return extract_query_from_messages(
        [{"role": "user", "content": task_prompt or prompt_input or ""}]
    ) or ""


async def build_agent_preview(
    db: AsyncSession,
    agent: AgentDTO,
    *,
    task_type: str | None = None,
    project_id: str | None = None,
    phase: str | None = None,
    prompt_input: str | None = None,
) -> dict[str, Any]:
    """Preview the exact canonical operator delivery plus agent-specific layers."""
    agent_memory_config = agent.memory_config
    include_mandates, include_guardrails, include_references = resolve_memory_config_includes(
        agent_memory_config
    )
    injection_enabled = memory_injection_enabled(agent_memory_config)
    runtime_include_mandates, runtime_include_guardrails = resolve_runtime_prompt_includes(
        agent_memory_config
    )
    preview_consumer_profile = resolve_memory_consumer_profile(
        agent_memory_config,
        surface="preview",
    )

    task_prompt = await _build_task_prompt_preview(
        agent,
        task_type=task_type,
        project_id=project_id,
        phase=phase,
        prompt_input=prompt_input,
    )
    task_prompt_section = (
        RuntimePromptSection(
            label="Task Prompt",
            source_kind="task_prompt",
            source_id=task_type or "task",
            placement="user",
            content=task_prompt,
        )
        if task_prompt
        else None
    )

    memory_query = _build_preview_memory_query(task_prompt, prompt_input)
    audience_tags, exclude_tags = resolve_memory_tags(agent_memory_config)
    settings = await get_memory_settings(db)
    continuity_enabled, max_sessions, cross_project, live_sessions = (
        resolve_continuity_settings(settings, agent_memory_config)
    )
    delivery = await build_canonical_context_delivery(
        db,
        CanonicalContextDeliveryRequest(
            consumer_surface="agent_preview",
            consumer_profile=preview_consumer_profile,
            agent_slug=agent.slug,
            consumer_tags=audience_tags,
            project_id=project_id,
            task=task_prompt,
            query=memory_query or None,
            task_type=None if task_type == "chat" else task_type,
            phase=phase,
            include_prompts=True,
            include_memories=injection_enabled,
            include_mandates=include_mandates and runtime_include_mandates,
            include_guardrails=include_guardrails and runtime_include_guardrails,
            include_references=include_references,
            include_reference_index=resolve_reference_index_enabled(agent_memory_config),
            exclude_tags=exclude_tags,
            exclude_memory_uuids=resolve_excluded_memory_uuids(agent_memory_config),
            include_project_index=resolve_project_index_enabled(agent_memory_config),
            include_tool_capabilities=resolve_tool_capabilities_enabled(agent_memory_config),
            include_continuity=continuity_enabled,
            continuity_max_sessions=max_sessions,
            continuity_cross_project=cross_project,
            continuity_live_sessions=live_sessions,
        ),
    )
    context = progressive_context_from_delivery(delivery)

    canonical_sections = [
        RuntimePromptSection(
            label=block.title,
            source_kind=f"canonical_{block.kind}",
            source_id=block.provenance.source_id,
            placement="system",
            content=block.content,
        )
        for block in delivery.blocks
    ]
    if delivery.status != "ok":
        canonical_sections.append(
            RuntimePromptSection(
                label="Canonical Context Failure",
                source_kind="canonical_context_failure",
                source_id=delivery.delivery_id,
                placement="system",
                content=delivery.rendered,
            )
        )

    agent_sections = await collect_runtime_prompt_sections(
        db,
        agent,
        task_type=None if task_type == "chat" else task_type,
        project_id=project_id,
        include_global_prompts=False,
        include_persona_context=True,
    )
    preview_sections = [*canonical_sections, *agent_sections]
    if task_prompt_section:
        preview_sections.append(task_prompt_section)

    telemetry = _build_budget_telemetry(preview_sections, [])

    mandate_uuids = [m.uuid[:8] if m.uuid else "" for m in context.mandates]
    guardrail_uuids = [g.uuid[:8] if g.uuid else "" for g in context.guardrails]
    agent_prompt = join_runtime_prompt_sections(agent_sections)
    combined = "\n\n".join(
        content for content in (delivery.rendered, agent_prompt) if content
    )
    full_context = "\n\n".join(
        content for content in (combined, task_prompt or "") if content
    )

    return {
        "combined_prompt": combined,
        "full_context": full_context,
        "memory_query": memory_query,
        "memory_debug": dict(getattr(context, "debug_info", {})),
        "loaded_memory_uuids": context.get_loaded_uuids(),
        "reference_uuids": context.get_reference_uuids(),
        "reference_index_uuids": context.get_reference_index_uuids(),
        "mandate_count": len(context.mandates),
        "guardrail_count": len(context.guardrails),
        "mandate_uuids": [u for u in mandate_uuids if u],
        "guardrail_uuids": [u for u in guardrail_uuids if u],
        "task_type": task_type,
        "phase": phase,
        "project_id": project_id,
        "task_prompt": task_prompt,
        "sections": [section.to_preview_dict() for section in preview_sections],
        "prompt_budget": telemetry,
        "full_context_estimated_tokens": count_tokens(full_context) if full_context else 0,
        "canonical_context": canonical_context_contract(delivery),
    }
