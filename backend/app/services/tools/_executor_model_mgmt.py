"""Model management tool implementations for DirectToolExecutor.

Handles model listing, details, agent model updates, benchmarks, and agent listing.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Re-export helpers that tests import transitively via this module.
from app.services.tools._executor_model_mgmt_helpers import (  # noqa: E402, F401
    _apply_tag_patches,
    _build_changes_summary,
    _compute_model_line,
    _copy_memory_config,
    _do_update_agent_memory,
    _do_update_agent_model,
    _format_agent_details,
    _format_catalog_cost,
    _format_enrichment_lines,
    _merge_tag_values,
    _normalize_tag_values,
    _resolve_catalog_model_id,
)


async def list_models() -> str:
    """List all catalog models with merged benchmark scores."""
    try:
        from app.constants import MODEL_CATALOG
        from app.db import async_session
        from app.services.model_enrichment_service import get_all_enrichments

        enrichments: dict = {}
        try:
            async with async_session() as db:
                enrichments = await get_all_enrichments(db)
        except Exception:
            logger.debug("Failed to load model enrichments", exc_info=True)

        lines = [_compute_model_line(m, enrichments) for m in MODEL_CATALOG]
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
            f"  {_format_catalog_cost(entry.cost)}",
            "",
            "## Capabilities",
            f"  Vision: {entry.capabilities.has_vision} | Thinking: {entry.capabilities.has_thinking}",
            f"  Image Gen: {entry.capabilities.can_generate_images} | "
            f"PDF: {entry.capabilities.supports_pdf} | Audio: {entry.capabilities.supports_audio}",
            f"  Max Output: {entry.capabilities.max_output_tokens:,} tokens",
        ]
        if enr:
            lines.extend(_format_enrichment_lines(enr))
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
    """Update an agent's manual routing model chain and inference knobs."""
    if not agent_slug:
        return "Error: agent_slug required for update_agent_model"
    if not any([primary_model_id, fallback_models, escalation_model_id,
                temperature is not None, thinking_level]):
        return "Error: at least one setting to update required"
    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models import AgentRoutingProfile, ManualModelRoute
        from app.services.agent_service import get_agent_service

        agent_service = get_agent_service()
        resolved_primary = _resolve_catalog_model_id(primary_model_id)
        resolved_fallbacks = (
            [_resolve_catalog_model_id(mid) or mid for mid in fallback_models]
            if fallback_models else None
        )
        resolved_escalation = _resolve_catalog_model_id(escalation_model_id)

        async with async_session() as db:
            agent = await agent_service.get_by_slug(db, agent_slug)
            if not agent:
                return f"Error: Agent '{agent_slug}' not found"

            updated = agent
            if temperature is not None or thinking_level:
                updated = await agent_service.update(
                    db,
                    agent.id,
                    temperature=temperature,
                    thinking_level=thinking_level,
                    changed_by="persona",
                    change_reason=change_reason or "Routing/inference update by persona",
                )
                if not updated:
                    return f"Error: Failed to update agent '{agent_slug}'"

            if any([resolved_primary, resolved_fallbacks is not None, resolved_escalation]):
                primary = resolved_primary or agent.primary_model_id
                fallbacks = resolved_fallbacks if resolved_fallbacks is not None else list(agent.fallback_models or [])
                route = await db.scalar(
                    select(ManualModelRoute).where(
                        ManualModelRoute.agent_slug == agent_slug,
                        ManualModelRoute.workload_profile.is_(None),
                        ManualModelRoute.enabled == True,  # noqa: E712
                    )
                )
                if route is None:
                    route = ManualModelRoute(agent_slug=agent_slug, workload_profile=None)
                    db.add(route)
                route.primary_model_id = primary
                route.fallback_models = fallbacks
                route.escalation_model_id = resolved_escalation if escalation_model_id is not None else agent.escalation_model_id
                route.reason = change_reason or "Manual route update by persona"
                route.owner = "persona"
                route.enabled = True
                profile = await db.get(AgentRoutingProfile, agent_slug)
                if profile is None:
                    profile = AgentRoutingProfile(agent_slug=agent_slug)
                    db.add(profile)
                profile.default_routing_mode = "manual_locked"
                metadata = dict(profile.metadata_ or {})
                metadata["source"] = "manual_override"
                profile.metadata_ = metadata
            await db.commit()

        if updated is None:
            return f"Error: Agent '{agent_slug}' not found"
        if not updated:
            return f"Error: Failed to update agent '{agent_slug}'"

        changes = _build_changes_summary(
            resolved_primary, resolved_fallbacks, resolved_escalation,
            temperature, thinking_level,
        )
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
        patch, add_audience_tags, remove_audience_tags, clear_audience_tags,
        add_exclude_tags, remove_exclude_tags, clear_exclude_tags,
    ]):
        return "Error: at least one memory update is required"

    try:
        from app.services.agent_service import get_agent_service

        agent_service = get_agent_service()
        updated, updated_config = await _do_update_agent_memory(
            agent_service, agent_slug, patch,
            add_audience_tags, remove_audience_tags, clear_audience_tags,
            add_exclude_tags, remove_exclude_tags, clear_exclude_tags,
            change_reason,
        )

        if updated is None:
            return f"Error: Agent '{agent_slug}' not found"
        if updated == "noop":
            return f"No memory config changes required for agent '{agent_slug}'."
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

        return "\n\n".join(_format_agent_details(a) for a in agents)
    except Exception as e:
        logger.exception("list_agents failed")
        return f"Error listing agents: {e}"
