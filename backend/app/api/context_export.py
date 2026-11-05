"""Read-only, bounded context datasets for the Aico importer."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.access_control_auth import require_service_client

router = APIRouter(prefix="/context-export", tags=["context-export"])

# The JSON text and field order are the existing importer contract. In
# particular, project_rows keeps the table's physical column order and its hash
# joins those exact strings with one newline, without a trailing newline.
_QUERIES = {
    "memories": """SELECT row_to_json(t)::text FROM (SELECT id, group_id, scope, scope_id, summary, content,
        tags, tier, pinned, render_mode, trigger_task_types, applicability, loaded_count, helpful_count,
        harmful_count, version, created_at, updated_at FROM memories WHERE status = 'active' ORDER BY id
        OFFSET :offset LIMIT :fetch_limit) t""",
    "memory_settings": """SELECT row_to_json(t)::text FROM (SELECT enabled, total_budget, budget_enabled,
        max_mandates, max_guardrails, reference_index_enabled, continuity_enabled,
        continuity_max_sessions, active_variant FROM memory_settings ORDER BY id
        OFFSET :offset LIMIT :fetch_limit) t""",
    "prompts": """SELECT row_to_json(t)::text FROM (SELECT id, slug, name, description, content,
        prompt_type, is_global, boot_eligible, context_policy, updated_at FROM prompts
        WHERE enabled ORDER BY id OFFSET :offset LIMIT :fetch_limit) t""",
    "agents": """SELECT row_to_json(t)::text FROM (SELECT a.slug, a.name,
        a.description, a.updated_at, (SELECT jsonb_agg(ap.prompt_id ORDER BY ap.priority, ap.prompt_id)
          FROM agent_prompts ap JOIN prompts p ON p.id = ap.prompt_id AND p.enabled
          WHERE ap.agent_id = a.id) AS prompt_ids
        FROM agents a WHERE a.slug IN :agent_roles
        ORDER BY a.slug OFFSET :offset LIMIT :fetch_limit) t""",
    "budgets": """SELECT row_to_json(t)::text FROM (SELECT harness, role, warn_tokens, jump_pct, note,
        updated_at FROM context_budgets ORDER BY harness, role
        OFFSET :offset LIMIT :fetch_limit) t""",
    "project_rows": """SELECT row_to_json(p)::text FROM project_permissions p ORDER BY id
        OFFSET :offset LIMIT :fetch_limit""",
    "project_hash": """SELECT to_json(encode(sha256(convert_to(coalesce(
        string_agg(row_to_json(p)::text, E'\\n' ORDER BY id), ''), 'UTF8')), 'hex'))::text
        FROM project_permissions p OFFSET :offset LIMIT :fetch_limit""",
}


class ContextExportPage(BaseModel):
    rows: list[str]
    next_offset: int | None


@router.get("/{collection}", response_model=ContextExportPage)
async def export_context(
    collection: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 1000,
    agent_role: Annotated[list[str] | None, Query()] = None,
) -> ContextExportPage:
    """Export one page of a named dataset using a registered service identity."""
    await require_service_client(request)
    query = _QUERIES.get(collection)
    if query is None:
        raise HTTPException(status_code=404, detail="Unknown context export collection.")
    params: dict[str, Any] = {"offset": offset, "fetch_limit": limit + 1}
    statement = text(query)
    if collection == "agents":
        if not agent_role or any(
            len(role) > 50 or re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", role) is None
            for role in agent_role
        ):
            raise HTTPException(status_code=422, detail="Explicit valid agent role slugs are required.")
        statement = statement.bindparams(bindparam("agent_roles", expanding=True))
        params["agent_roles"] = agent_role
    elif agent_role:
        raise HTTPException(status_code=422, detail="Agent roles apply only to the agents collection.")
    try:
        # get_db supplies a fresh session and rolls back when the request ends.
        # This must precede the SELECT, including the aggregate hash query.
        await db.execute(text("SET TRANSACTION READ ONLY"))
        result = await db.execute(statement, params)
        rows = list(result.scalars().all())
    except SQLAlchemyError:
        # Database exceptions can contain values. Do not log or return them.
        raise HTTPException(status_code=503, detail="Context export is unavailable.") from None
    return ContextExportPage(rows=rows[:limit], next_offset=offset + limit if len(rows) > limit else None)
