"""Helper utilities for _executor_model_mgmt.

Contains pure helper functions: alias resolution, tag normalization, formatting,
and async DB helpers that keep public-facing functions under 50 lines.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.memory.context_builder_settings import normalize_memory_config


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


def _format_catalog_cost(cost: Any) -> str:
    """Return a human-readable cost summary for catalog entries."""
    pricing_unit = getattr(cost, "pricing_unit", "per_million_tokens")
    if pricing_unit != "per_million_tokens":
        unit_price = getattr(cost, "unit_price", None)
        unit_labels = {
            "per_image": "image",
            "per_second": "second",
            "per_minute": "minute",
            "per_million_characters": "1M chars",
        }
        unit_label = unit_labels.get(pricing_unit, pricing_unit.replace("per_", ""))
        if unit_price in (None, 0):
            return f"free per {unit_label}"
        return f"${unit_price}/{unit_label}"
    return f"${cost.input_per_m}/M in, ${cost.output_per_m}/M out"


def _compute_model_line(m: Any, enrichments: dict) -> str:
    """Build the formatted listing line for a single catalog model."""
    from app.constants.catalog import SCORE_WEIGHTS

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

    return (
        f"- **{m.name}** (`{m.id}`)\n"
        f"  Provider: {m.provider} | Speed: {m.speed_tier} | "
        f"Context: {m.context_window:,} | Family: {m.family or 'N/A'}\n"
        f"  Scores: coding={coding} reasoning={reasoning} "
        f"planning={planning} tool_use={tool_use} "
        f"instruction={instruction} design={design} "
        f"composite={composite}\n"
        f"  Cost: {_format_catalog_cost(m.cost)}\n"
        f"  Capabilities: {', '.join(cap_flags) or 'none'}"
    )


def _format_enrichment_lines(enr: Any) -> list[str]:
    """Return formatted lines for an external enrichment record."""
    return [
        "",
        "## External Enrichment",
        f"  Ext Coding: {enr.ext_coding or 'N/A'} | Ext Reasoning: {enr.ext_reasoning or 'N/A'}",
        f"  Ext Speed: {enr.ext_speed_tier or 'N/A'}",
        f"  Ext Pricing: ${enr.ext_input_per_m or 'N/A'}/M in, "
        f"${enr.ext_output_per_m or 'N/A'}/M out",
        f"  Source: {enr.source} | Synced: {enr.synced_at.isoformat() if enr.synced_at else 'never'}",
    ]


def _build_changes_summary(
    resolved_primary_model_id: str | None,
    resolved_fallback_models: list[str] | None,
    resolved_escalation_model_id: str | None,
    temperature: float | None,
    thinking_level: str | None,
) -> list[str]:
    """Collect human-readable change descriptions for update_agent_model."""
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
    return changes


def _apply_tag_patches(
    updated_config: dict[str, object],
    patch: dict[str, object],
    *,
    add_audience_tags: list[str] | None,
    remove_audience_tags: list[str] | None,
    clear_audience_tags: bool,
    add_exclude_tags: list[str] | None,
    remove_exclude_tags: list[str] | None,
    clear_exclude_tags: bool,
) -> None:
    """Mutate updated_config in-place to apply audience/exclude tag operations."""
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


async def _do_update_agent_model(
    agent_service: Any,
    agent_slug: str,
    resolved_primary: str | None,
    resolved_fallbacks: list[str] | None,
    resolved_escalation: str | None,
    temperature: float | None,
    thinking_level: str | None,
    change_reason: str | None,
) -> Any:
    """Perform the DB fetch-and-update for update_agent_model; return updated record."""
    from app.db import async_session

    async with async_session() as db:
        agent = await agent_service.get_by_slug(db, agent_slug)
        if not agent:
            return None
        updated = await agent_service.update(
            db, agent.id,
            primary_model_id=resolved_primary,
            fallback_models=resolved_fallbacks,
            escalation_model_id=resolved_escalation,
            temperature=temperature,
            thinking_level=thinking_level,
            changed_by="persona",
            change_reason=change_reason or "Model config update by persona",
        )
    return updated


async def _do_update_agent_memory(
    agent_service: Any,
    agent_slug: str,
    patch: dict[str, object],
    add_audience_tags: list[str] | None,
    remove_audience_tags: list[str] | None,
    clear_audience_tags: bool,
    add_exclude_tags: list[str] | None,
    remove_exclude_tags: list[str] | None,
    clear_exclude_tags: bool,
    change_reason: str | None,
) -> tuple[Any, dict[str, object] | None]:
    """Perform the DB fetch, config merge, and update for update_agent_memory.

    Returns (updated_record, updated_config) where updated_config is None when no change.
    """
    from app.db import async_session

    async with async_session() as db:
        agent = await agent_service.get_by_slug(db, agent_slug)
        if not agent:
            return None, None

        current_config = _copy_memory_config(getattr(agent, "memory_config", None))
        updated_config = dict(current_config)
        updated_config.update(patch)
        _apply_tag_patches(
            updated_config, patch,
            add_audience_tags=add_audience_tags,
            remove_audience_tags=remove_audience_tags,
            clear_audience_tags=clear_audience_tags,
            add_exclude_tags=add_exclude_tags,
            remove_exclude_tags=remove_exclude_tags,
            clear_exclude_tags=clear_exclude_tags,
        )

        if updated_config == current_config:
            return "noop", updated_config

        updated = await agent_service.update(
            db, agent.id,
            memory_config=updated_config,
            changed_by="persona",
            change_reason=change_reason or "Memory config update by persona",
        )
    return updated, updated_config
