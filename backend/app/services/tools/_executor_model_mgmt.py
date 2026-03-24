"""Model management tool implementations for DirectToolExecutor.

Handles model listing, details, agent model updates, benchmarks, and agent listing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.memory.context_builder_settings import normalize_memory_config

logger = logging.getLogger(__name__)


def _resolve_catalog_model_id(model_id: str | None) -> str | None:
    """Resolve aliases to canonical catalog IDs for model-management actions."""
    if not model_id:
        return None

    from app.constants.catalog import MODEL_CATALOG_BY_ID, resolve_model

    resolved = resolve_model(model_id)
    if resolved in MODEL_CATALOG_BY_ID:
        return resolved
    return model_id


def _normalize_tag_values(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        cleaned = value.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _merge_tag_values(
    current: object,
    *,
    add_values: list[str] | None = None,
    remove_values: list[str] | None = None,
    clear: bool = False,
) -> list[str]:
    merged = [] if clear else _normalize_tag_values(current if isinstance(current, list) else None)
    for value in _normalize_tag_values(add_values):
        if value not in merged:
            merged.append(value)
    remove_set = set(_normalize_tag_values(remove_values))
    if remove_set:
        merged = [value for value in merged if value not in remove_set]
    return merged


def _copy_memory_config(memory_config: object) -> dict[str, object]:
    normalized = normalize_memory_config(memory_config if isinstance(memory_config, dict) else None)
    return dict(normalized) if normalized else {}


def _format_agent_details(agent: Any) -> str:
    memory_config = getattr(agent, "memory_config", None)
    fallback_models = getattr(agent, "fallback_models", None) or []
    fallbacks = ", ".join(fallback_models) if fallback_models else "none"
    description = getattr(agent, "description", None)
    description_block = f"\n  Description: {description}" if description else ""
    memory_config_json = json.dumps(memory_config or {}, sort_keys=True)
    return (
        f"- **{agent.name}** (`{agent.slug}`){description_block}\n"
        f"  Primary: {agent.primary_model_id} | Fallbacks: {fallbacks}\n"
        f"  Escalation: {agent.escalation_model_id or 'none'} | "
        f"Temp: {agent.temperature} | Thinking: {agent.thinking_level or 'N/A'}\n"
        f"  Role: {'coding' if agent.is_coding_agent else 'general'} | "
        f"Active: {agent.is_active} | Version: {agent.version}\n"
        f"  Memory: {memory_config_json}"
    )


async def list_models() -> str:
    """List all catalog models with merged benchmark scores."""
    try:
        from app.constants import MODEL_CATALOG
        from app.constants.catalog import SCORE_WEIGHTS
        from app.db import async_session
        from app.services.model_enrichment_service import get_all_enrichments

        enrichments: dict = {}
        try:
            async with async_session() as db:
                enrichments = await get_all_enrichments(db)
        except Exception:
            logger.debug("Failed to load model enrichments", exc_info=True)

        lines = []
        for m in MODEL_CATALOG:
            cap_flags = []
            if m.capabilities.has_vision:
                cap_flags.append("vision")
            if m.capabilities.has_thinking:
                cap_flags.append("thinking")
            if m.capabilities.can_generate_images:
                cap_flags.append("image-gen")
            if m.capabilities.supports_pdf:
                cap_flags.append("pdf")
            if m.capabilities.supports_audio:
                cap_flags.append("audio")

            enr = enrichments.get(m.id)
            coding = enr.ext_coding if enr and enr.ext_coding is not None else m.scores.coding
            reasoning = enr.ext_reasoning if enr and enr.ext_reasoning is not None else m.scores.reasoning
            tool_use = enr.ext_tool_use if enr and enr.ext_tool_use is not None else m.scores.tool_use
            planning = enr.ext_planning if enr and enr.ext_planning is not None else m.scores.planning
            instruction = enr.ext_instruction if enr and enr.ext_instruction is not None else m.scores.instruction
            design = m.scores.design
            composite = round(
                coding * SCORE_WEIGHTS["coding"]
                + reasoning * SCORE_WEIGHTS["reasoning"]
                + planning * SCORE_WEIGHTS["planning"]
                + tool_use * SCORE_WEIGHTS["tool_use"]
                + instruction * SCORE_WEIGHTS["instruction"]
                + design * SCORE_WEIGHTS["design"],
                1,
            )

            lines.append(
                f"- **{m.name}** (`{m.id}`)\n"
                f"  Provider: {m.provider} | Speed: {m.speed_tier} | "
                f"Context: {m.context_window:,} | Family: {m.family or 'N/A'}\n"
                f"  Scores: coding={coding} reasoning={reasoning} "
                f"planning={planning} tool_use={tool_use} "
                f"instruction={instruction} design={design} "
                f"composite={composite}\n"
                f"  Cost: ${m.cost.input_per_m}/M in, ${m.cost.output_per_m}/M out\n"
                f"  Capabilities: {', '.join(cap_flags) or 'none'}"
            )
        return "\n\n".join(lines)
    except Exception as e:
        logger.exception("list_models failed")
        return f"Error listing models: {e}"


async def get_model_details(model_id: str | None) -> str:
    """Get detailed info for a specific model including enrichments."""
    if not model_id:
        return "Error: model_id required for get_model_details"
    try:
        from app.constants import MODEL_CATALOG
        from app.db import async_session
        from app.services.model_enrichment_service import get_all_enrichments

        resolved_model_id = _resolve_catalog_model_id(model_id)
        entry = next((m for m in MODEL_CATALOG if m.id == resolved_model_id), None)
        if not entry:
            return f"Error: Model '{model_id}' not found in catalog"

        async with async_session() as db:
            enrichments = await get_all_enrichments(db)
        enr = enrichments.get(entry.id)

        lines = [
            f"# {entry.name} ({entry.id})",
            f"Provider: {entry.provider} | Alias: @{entry.alias} | Family: {entry.family or 'N/A'}",
            f"Speed: {entry.speed_tier} | Context: {entry.context_window:,} tokens",
            f"Release: {entry.release_date or 'N/A'} | Cutoff: {entry.knowledge_cutoff or 'N/A'}",
            "",
            "## Scores",
            f"  Coding: {entry.scores.coding} | Reasoning: {entry.scores.reasoning} | "
            f"Planning: {entry.scores.planning}",
            f"  Tool Use: {entry.scores.tool_use} | Instruction: {entry.scores.instruction} | "
            f"Design: {entry.scores.design}",
            f"  Composite: {entry.scores.composite}",
            "",
            "## Cost",
            f"  Input: ${entry.cost.input_per_m}/M | Output: ${entry.cost.output_per_m}/M",
            "",
            "## Capabilities",
            f"  Vision: {entry.capabilities.has_vision} | Thinking: {entry.capabilities.has_thinking}",
            f"  Image Gen: {entry.capabilities.can_generate_images} | "
            f"PDF: {entry.capabilities.supports_pdf} | Audio: {entry.capabilities.supports_audio}",
            f"  Max Output: {entry.capabilities.max_output_tokens:,} tokens",
        ]

        if enr:
            lines.extend([
                "",
                "## External Enrichment",
                f"  Ext Coding: {enr.ext_coding or 'N/A'} | Ext Reasoning: {enr.ext_reasoning or 'N/A'}",
                f"  Ext Speed: {enr.ext_speed_tier or 'N/A'}",
                f"  Ext Pricing: ${enr.ext_input_per_m or 'N/A'}/M in, "
                f"${enr.ext_output_per_m or 'N/A'}/M out",
                f"  Source: {enr.source} | Synced: {enr.synced_at.isoformat() if enr.synced_at else 'never'}",
            ])

        return "\n".join(lines)
    except Exception as e:
        logger.exception("get_model_details failed")
        return f"Error getting model details: {e}"


async def update_agent_model(
    agent_slug: str | None,
    primary_model_id: str | None,
    fallback_models: list[str] | None,
    escalation_model_id: str | None,
    temperature: float | None,
    thinking_level: str | None,
    change_reason: str | None,
) -> str:
    """Update an agent's model configuration."""
    if not agent_slug:
        return "Error: agent_slug required for update_agent_model"
    if not any([
        primary_model_id, fallback_models, escalation_model_id,
        temperature is not None, thinking_level,
    ]):
        return "Error: at least one setting to update required"

    try:
        from app.db import async_session
        from app.services.agent_service import get_agent_service

        agent_service = get_agent_service()
        resolved_primary_model_id = _resolve_catalog_model_id(primary_model_id)
        resolved_fallback_models = (
            [_resolve_catalog_model_id(model_id) or model_id for model_id in fallback_models]
            if fallback_models
            else None
        )
        resolved_escalation_model_id = _resolve_catalog_model_id(escalation_model_id)

        async with async_session() as db:
            agent = await agent_service.get_by_slug(db, agent_slug)
            if not agent:
                return f"Error: Agent '{agent_slug}' not found"

            updated = await agent_service.update(
                db,
                agent.id,
                primary_model_id=resolved_primary_model_id,
                fallback_models=resolved_fallback_models,
                escalation_model_id=resolved_escalation_model_id,
                temperature=temperature,
                thinking_level=thinking_level,
                changed_by="persona",
                change_reason=change_reason or "Model config update by persona",
            )

        if not updated:
            return f"Error: Failed to update agent '{agent_slug}'"

        changes = []
        if resolved_primary_model_id:
            changes.append(f"primary_model={resolved_primary_model_id}")
        if resolved_fallback_models:
            changes.append(f"fallback_models={resolved_fallback_models}")
        if resolved_escalation_model_id:
            changes.append(f"escalation_model={resolved_escalation_model_id}")
        if temperature is not None:
            changes.append(f"temperature={temperature}")
        if thinking_level:
            changes.append(f"thinking_level={thinking_level}")

        return (
            f"Agent '{agent_slug}' updated (version {updated.version}). "
            f"Changes: {', '.join(changes)}. Reason: {change_reason or 'N/A'}"
        )
    except Exception as e:
        logger.exception("update_agent_model failed")
        return f"Error updating agent model: {e}"


async def get_agent_details(agent_slug: str | None) -> str:
    """Inspect a single agent including its memory configuration."""
    if not agent_slug:
        return "Error: agent_slug required for get_agent_details"

    try:
        from app.db import async_session
        from app.services.agent_service import get_agent_service

        agent_service = get_agent_service()
        async with async_session() as db:
            agent = await agent_service.get_by_slug(db, agent_slug)

        if not agent:
            return f"Error: Agent '{agent_slug}' not found"

        return _format_agent_details(agent)
    except Exception as e:
        logger.exception("get_agent_details failed")
        return f"Error getting agent details: {e}"


async def update_agent_memory(
    agent_slug: str | None,
    memory_config_patch: dict[str, object] | None,
    add_audience_tags: list[str] | None,
    remove_audience_tags: list[str] | None,
    clear_audience_tags: bool,
    add_exclude_tags: list[str] | None,
    remove_exclude_tags: list[str] | None,
    clear_exclude_tags: bool,
    change_reason: str | None,
) -> str:
    """Patch an agent's memory configuration without replacing the whole blob."""
    if not agent_slug:
        return "Error: agent_slug required for update_agent_memory"

    patch = _copy_memory_config(memory_config_patch)
    if not any([
        patch,
        add_audience_tags,
        remove_audience_tags,
        clear_audience_tags,
        add_exclude_tags,
        remove_exclude_tags,
        clear_exclude_tags,
    ]):
        return "Error: at least one memory update is required"

    try:
        from app.db import async_session
        from app.services.agent_service import get_agent_service

        agent_service = get_agent_service()

        async with async_session() as db:
            agent = await agent_service.get_by_slug(db, agent_slug)
            if not agent:
                return f"Error: Agent '{agent_slug}' not found"

            current_config = _copy_memory_config(getattr(agent, "memory_config", None))
            updated_config = dict(current_config)
            updated_config.update(patch)

            if (
                "audience_tags" in patch
                or add_audience_tags
                or remove_audience_tags
                or clear_audience_tags
            ):
                updated_config["audience_tags"] = _merge_tag_values(
                    updated_config.get("audience_tags"),
                    add_values=add_audience_tags,
                    remove_values=remove_audience_tags,
                    clear=clear_audience_tags,
                )

            if (
                "exclude_tags" in patch
                or add_exclude_tags
                or remove_exclude_tags
                or clear_exclude_tags
            ):
                updated_config["exclude_tags"] = _merge_tag_values(
                    updated_config.get("exclude_tags"),
                    add_values=add_exclude_tags,
                    remove_values=remove_exclude_tags,
                    clear=clear_exclude_tags,
                )

            if updated_config == current_config:
                return f"No memory config changes required for agent '{agent_slug}'."

            updated = await agent_service.update(
                db,
                agent.id,
                memory_config=updated_config,
                changed_by="persona",
                change_reason=change_reason or "Memory config update by persona",
            )

        if not updated:
            return f"Error: Failed to update agent '{agent_slug}'"

        return (
            f"Agent '{agent_slug}' memory updated (version {updated.version}). "
            f"Memory config: {json.dumps(updated_config, sort_keys=True)}. "
            f"Reason: {change_reason or 'N/A'}"
        )
    except Exception as e:
        logger.exception("update_agent_memory failed")
        return f"Error updating agent memory: {e}"


async def get_benchmarks() -> str:
    """Fetch and display latest external benchmark data."""
    try:
        from app.db import async_session
        from app.services.model_enrichment_service import sync_all

        async with async_session() as db:
            result = await sync_all(db)

        return (
            f"Benchmark sync complete.\n"
            f"Status: {result['status']}\n"
            f"Enriched: {result['enriched']}/{result['total']} models\n"
            f"Sources: models.dev={result.get('sources', {}).get('models_dev', 0)} entries, "
            f"benchmarks={result.get('sources', {}).get('benchmarks', 0)} entries\n"
            f"Synced at: {result.get('synced_at', 'N/A')}"
        )
    except Exception as e:
        logger.exception("get_benchmarks failed")
        return f"Error fetching benchmarks: {e}"


async def list_agents(fmt: str = "detailed", coding_only: bool | None = None) -> str:
    """List all agents with their current model configurations.

    Args:
        fmt: "detailed" (full config per agent) or "compact" (one-liner, active only).
        coding_only: Optional coding-agent filter. True=coding only, False=non-coding only.
    """
    try:
        from app.db import async_session
        from app.services.agent_service import get_agent_service

        agent_service = get_agent_service()
        active_only = fmt == "compact"
        async with async_session() as db:
            agents = await agent_service.list_agents(
                db, active_only=active_only, coding_only=coding_only
            )

        if not agents:
            return "(No agents configured)"

        if fmt == "compact":
            lines = [
                f"- {a.slug} [{'coding' if a.is_coding_agent else 'general'}]: "
                f"{a.description or '(no description)'}"
                for a in agents
            ]
            return "\n".join(lines)

        lines = []
        for a in agents:
            lines.append(_format_agent_details(a))
        return "\n\n".join(lines)
    except Exception as e:
        logger.exception("list_agents failed")
        return f"Error listing agents: {e}"
