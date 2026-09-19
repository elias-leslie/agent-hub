"""Identity of the actual review inputs, without credentials or wall-clock churn."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.context_policy import semantic_hash


async def reviewer_identity(db: AsyncSession, *, schema: dict[str, Any], instruction: str,
                            agent_slug: str = "memory-curator", model_id: str | None = None) -> str:
    from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

    try:
        resolved = await resolve_agent(agent_slug, db)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return semantic_hash({"agent": agent_slug, "unavailable": True, "schema": schema, "instruction": instruction})
    mandate = await inject_agent_mandates(resolved.agent, db, prompt_mode="minimal",
        project_id="agent-hub", task_type="review")
    return semantic_hash({"agent": agent_slug, "model": model_id or resolved.model,
        "fallbacks": resolved.agent.fallback_models, "prompt": mandate.system_content,
        "temperature": resolved.agent.temperature, "thinking": resolved.agent.thinking_level,
        "schema": schema, "instruction": instruction})
