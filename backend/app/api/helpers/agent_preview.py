"""Agent preview helper functions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_dto import AgentDTO
from app.services.memory.context_builder_settings import (
    memory_injection_enabled,
    resolve_memory_config_includes,
    resolve_runtime_prompt_includes,
)
from app.services.memory.context_injector import (
    build_progressive_context,
    extract_query_from_messages,
    format_progressive_context,
)
from app.services.memory.service import MemoryScope
from app.services.runtime_prompt_stack import (
    RuntimePromptSection,
    collect_runtime_prompt_sections,
    join_runtime_prompt_sections,
)


class _EmptyPreviewContext:
    def __init__(self) -> None:
        self.mandates: list[Any] = []
        self.guardrails: list[Any] = []
        self.debug_info: dict[str, Any] = {}

    def get_loaded_uuids(self) -> list[str]:
        return []

    def get_reference_uuids(self) -> list[str]:
        return []


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
        from app.workflows.persona_heartbeat import get_model_review_status

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
            consumer_profile="agent_preview",
        )
        formatted_memory = format_progressive_context(
            context,
            include_citations=True,
            consumer_profile="agent_preview",
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
    if task_prompt_section:
        runtime_sections.append(task_prompt_section)

    mandate_uuids = [m.uuid[:8] if m.uuid else "" for m in context.mandates]
    guardrail_uuids = [g.uuid[:8] if g.uuid else "" for g in context.guardrails]
    full_context = "\n\n".join(section.content for section in runtime_sections if section.content)

    return {
        "combined_prompt": combined,
        "full_context": full_context,
        "memory_query": memory_query,
        "memory_debug": dict(getattr(context, "debug_info", {})),
        "loaded_memory_uuids": context.get_loaded_uuids(),
        "reference_uuids": context.get_reference_uuids(),
        "mandate_count": len(context.mandates),
        "guardrail_count": len(context.guardrails),
        "mandate_uuids": [u for u in mandate_uuids if u],
        "guardrail_uuids": [u for u in guardrail_uuids if u],
        "task_type": task_type,
        "phase": phase,
        "project_id": project_id,
        "task_prompt": task_prompt,
        "sections": [section.to_preview_dict() for section in runtime_sections],
    }
