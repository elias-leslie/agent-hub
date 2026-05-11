"""Agent preview helper functions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_dto import AgentDTO
from app.services.memory.context_builder_settings import (
    memory_injection_enabled,
    resolve_memory_config_includes,
    resolve_memory_consumer_profile,
    resolve_project_index_enabled,
    resolve_runtime_prompt_includes,
    resolve_tool_capabilities_enabled,
)
from app.services.memory.context_injector import (
    build_progressive_context,
    extract_query_from_messages,
    format_progressive_context,
)
from app.services.memory.project_index_context import format_project_index_context
from app.services.memory.service import MemoryScope
from app.services.memory.tool_capability_context import format_tool_capability_context
from app.services.project_permission_service import get_visible_tools_for_project
from app.services.runtime_prompt_stack import (
    RuntimePromptSection,
    collect_runtime_prompt_sections,
    dedupe_runtime_prompt_sections,
    join_runtime_prompt_sections,
)
from app.services.token_counter import count_tokens

_PREVIEW_PROMPT_WARN_TOKENS = 3_200
_PREVIEW_PROMPT_DANGER_TOKENS = 4_500
_PREVIEW_LOW_YIELD_SOURCE_KINDS = {"persona_context", "memory_context", "task_prompt"}
_PREVIEW_LOW_YIELD_SHARE_WARN = 0.45
_PREVIEW_SECTION_SHARE_WARN = 0.2


class _EmptyPreviewContext:
    def __init__(self) -> None:
        self.mandates: list[Any] = []
        self.guardrails: list[Any] = []
        self.reference: list[Any] = []
        self.reference_index: list[Any] = []
        self.debug_info: dict[str, Any] = {}

    def get_loaded_uuids(self) -> list[str]:
        return []

    def get_reference_uuids(self) -> list[str]:
        return []

    def get_reference_index_uuids(self) -> list[str]:
        return []


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


def _render_budget_warning_section(telemetry: dict[str, Any]) -> str:
    warnings = telemetry.get("warnings") or []
    if not warnings:
        return ""
    top_sections = telemetry.get("top_sections") or []
    lines = [
        "<prompt_budget>",
        f"Severity: {telemetry['severity']}",
        f"Total estimated tokens: {telemetry['total_estimated_tokens']}",
        (
            "Thresholds: "
            f"warn={telemetry['warn_threshold_tokens']}, "
            f"danger={telemetry['danger_threshold_tokens']}"
        ),
        (
            "Low-yield tokens: "
            f"{telemetry['low_yield_estimated_tokens']} "
            f"across {telemetry['low_yield_section_count']} sections "
            f"({telemetry['low_yield_share_of_total']:.1%} of total)"
        ),
        "Warnings:",
        *[f"- {warning}" for warning in warnings],
    ]
    if top_sections:
        lines.append("Top sections:")
        lines.extend(
            f"- {section['label']} [{section['source_kind']}:{section['source_id']}] "
            f"~{section['estimated_tokens']} tokens ({section.get('share_of_total', 0.0):.1%})"
            for section in top_sections[:3]
        )
    hotspot_sections = telemetry.get("top_low_yield_sections") or []
    if hotspot_sections:
        lines.append("Low-yield hotspots:")
        lines.extend(
            f"- {section['label']} [{section['source_kind']}:{section['source_id']}] "
            f"~{section['estimated_tokens']} tokens ({section.get('share_of_total', 0.0):.1%})"
            for section in hotspot_sections
        )
    lines.append("</prompt_budget>")
    return "\n".join(lines)


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
        from app.adapters.registry import get_provider_for_model
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


def _memory_scope_for_project(project_id: str | None) -> tuple[MemoryScope, str | None]:
    if project_id:
        return MemoryScope.PROJECT, project_id
    return MemoryScope.GLOBAL, None


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
    """Build agent preview with runtime system sections, task prompt, and memory injection."""
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
    runtime_sections: list[RuntimePromptSection] = []
    runtime_sections = await collect_runtime_prompt_sections(
        db,
        agent,
        task_type=None if task_type == "chat" else task_type,
        project_id=project_id,
        include_global_prompts=True,
        include_mandates=runtime_include_mandates,
        include_guardrails=runtime_include_guardrails,
    )
    combined = join_runtime_prompt_sections(runtime_sections)
    project_index_block = ""
    if resolve_project_index_enabled(agent_memory_config):
        project_index_block = format_project_index_context(
            project_id,
            consumer_profile=preview_consumer_profile,
            task_type=task_type,
        )
        if project_index_block:
            combined = f"{combined}\n\n{project_index_block}" if combined else project_index_block
            runtime_sections.append(
                RuntimePromptSection(
                    label="Project Index",
                    source_kind="project_index",
                    source_id=project_id or "global",
                    placement="system",
                    content=project_index_block,
                )
            )
    tool_capability_block = ""
    if resolve_tool_capabilities_enabled(agent_memory_config):
        visible_tool_names = (
            await get_visible_tools_for_project(project_id, db)
            if project_id
            else frozenset()
        )
        bash_available = ("bash" in visible_tool_names) if project_id else None
        tool_capability_block = format_tool_capability_context(
            consumer_profile=preview_consumer_profile,
            task_type=task_type,
            project_id=project_id,
            bash_available=bash_available,
            agent_slug=agent.slug,
        )
        if tool_capability_block:
            combined = f"{combined}\n\n{tool_capability_block}" if combined else tool_capability_block
            runtime_sections.append(
                RuntimePromptSection(
                    label="Tool Capabilities",
                    source_kind="tool_capabilities",
                    source_id=agent.slug,
                    placement="system",
                    content=tool_capability_block,
                )
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

    scope, scope_id = _memory_scope_for_project(project_id)
    memory_query = _build_preview_memory_query(task_prompt, prompt_input)
    if injection_enabled:
        context = await build_progressive_context(
            query=memory_query,
            scope=scope,
            scope_id=scope_id,
            include_mandates=include_mandates,
            include_guardrails=include_guardrails,
            include_references=include_references,
            task_type=None if task_type == "chat" else task_type,
            phase=phase,
            memory_config=agent_memory_config,
            consumer_profile=preview_consumer_profile,
            consumer_agent_slug=agent.slug,
            consumer_tags=list(agent_memory_config.get("audience_tags", [])) if agent_memory_config else None,
        )
        formatted_memory = format_progressive_context(
            context,
            include_citations=True,
            consumer_profile=preview_consumer_profile,
        )
    else:
        context = _EmptyPreviewContext()
        formatted_memory = ""
    if formatted_memory:
        combined = f"{combined}\n\n{formatted_memory}" if combined else formatted_memory
        runtime_sections.append(
            RuntimePromptSection(
                label="Memory Context",
                source_kind="memory_context",
                source_id=scope_id or "global",
                placement="system",
                content=formatted_memory,
            )
        )

    runtime_sections, dropped_system_sections = dedupe_runtime_prompt_sections(runtime_sections)
    preview_sections = list(runtime_sections)
    if task_prompt_section:
        preview_sections.append(task_prompt_section)

    _, duplicate_sections = dedupe_runtime_prompt_sections(preview_sections)
    telemetry = _build_budget_telemetry(
        preview_sections,
        [*dropped_system_sections, *duplicate_sections],
    )

    mandate_uuids = [m.uuid[:8] if m.uuid else "" for m in context.mandates]
    guardrail_uuids = [g.uuid[:8] if g.uuid else "" for g in context.guardrails]
    combined = join_runtime_prompt_sections(
        [section for section in preview_sections if section.placement != "user"]
    )
    full_context = join_runtime_prompt_sections(preview_sections)
    reference_index_uuids_getter = getattr(context, "get_reference_index_uuids", None)
    reference_index_uuids = (
        reference_index_uuids_getter()
        if callable(reference_index_uuids_getter)
        else [
            r.uuid
            for r in getattr(context, "reference_index", [])
            if getattr(r, "uuid", None)
        ]
    )

    return {
        "combined_prompt": combined,
        "full_context": full_context,
        "memory_query": memory_query,
        "memory_debug": dict(getattr(context, "debug_info", {})),
        "loaded_memory_uuids": context.get_loaded_uuids(),
        "reference_uuids": context.get_reference_uuids(),
        "reference_index_uuids": reference_index_uuids,
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
    }
