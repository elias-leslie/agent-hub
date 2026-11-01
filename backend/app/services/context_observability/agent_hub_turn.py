"""First-turn context of Agent Hub's own agents (completions and agent runs routed through Agent Hub).

The total is the provider's own count from the first cost_logs row of the session, for rows `log_token_usage` writes.
Rows with another origin are left out (NOT_A_CALL_NOTES): `record_attempt_cost` writes one row per workflow attempt
holding the whole attempt's usage (native ones are measured from their transcripts, `via pi` ones from Pi's session
files), and `ingested from <source>` rows are other services' billed calls, not Agent Hub agents. Agent Hub is the harness, so there is no harness-vs-ours split by owner: the
bound delivery and the agent's runtime prompt stack are ours, the first user message is the brief, and what is left
(tool schemas, provider framing) is the harness remainder.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import first_turn

PROVIDER = "agent_hub"
# cost_note prefixes of rows that are not one agent call: workflow_runs/usage.py (whole attempts, with suffixes such as
# "; cost unknown") and api/cost_ingest.py (other services' calls). Matched with LIKE '<prefix>%', as the other cost readers do.
NOT_A_CALL_NOTES = ("workflow attempt", "ingested from")
LAUNCH_PREFIX = "agent:"

_FIRST_CALLS = text(
    """
    WITH first_call AS (
        SELECT DISTINCT ON (c.session_id) c.session_id, c.created_at, c.model, c.input_tokens,
               coalesce(c.cache_read_tokens, 0) AS cache_read, coalesce(c.cache_write_tokens, 0) AS cache_write
        FROM cost_logs c
        WHERE NOT EXISTS (  -- a session with such a row is not an agent session: its later rows are not a first call either
            SELECT 1 FROM cost_logs x
            WHERE x.session_id = c.session_id
              AND (coalesce(x.cost_note, '') LIKE :workflow_note OR coalesce(x.cost_note, '') LIKE :ingested_note)
        )
        ORDER BY c.session_id, c.created_at, c.id
    )
    SELECT f.*, s.agent_slug, s.project_id, s.request_source,
           (SELECT length(e.content) FROM session_events e
             WHERE e.session_id = f.session_id AND e.event_type = 'user_message'
             ORDER BY e.turn, e.sequence LIMIT 1) AS brief_chars
    FROM first_call f JOIN sessions s ON s.id = f.session_id
    WHERE f.created_at >= :since AND (CAST(:until AS timestamptz) IS NULL OR f.created_at <= :until)
      AND f.input_tokens + f.cache_read + f.cache_write > 0
    ORDER BY f.created_at
    """
)


async def first_calls(db: AsyncSession, *, since: datetime, until: datetime | None = None) -> list[dict[str, Any]]:
    """First priced call of every Agent Hub session whose first call falls in the window."""
    rows = (await db.execute(_FIRST_CALLS, {"workflow_note": f"{NOT_A_CALL_NOTES[0]}%", "ingested_note": f"{NOT_A_CALL_NOTES[1]}%", "since": since, "until": until})).mappings().all()
    return [dict(r) for r in rows]


def launch_mode_for(row: dict[str, Any]) -> str:
    return (LAUNCH_PREFIX + str(row.get("agent_slug") or row.get("request_source") or "unknown"))[:80]


async def stack_text(db: AsyncSession, slug: str | None) -> str | None:
    """The agent-specific runtime prompt stack as a real call assembles it now (global prompts are delivered separately)."""
    if not slug:
        return None
    from app.services.agent_crud import get_agent_by_slug
    from app.services.runtime_prompt_stack import (
        collect_runtime_prompt_sections,
        join_runtime_prompt_sections,
    )

    agent = await get_agent_by_slug(db, slug, active_only=False)
    if agent is None:
        return None
    sections = await collect_runtime_prompt_sections(db, agent, include_global_prompts=False)
    return join_runtime_prompt_sections(sections)


def compute_parts(
    row: dict[str, Any], *, stack: str | None, delivery: dict[str, Any] | None, stack_basis: str
) -> dict[str, Any]:
    """Stored parts for one Agent Hub first call. stack is None when the agent has no runtime stack we can read."""
    total = int(row["input_tokens"]) + int(row["cache_read"]) + int(row["cache_write"])
    brief = None if row.get("brief_chars") is None else first_turn.est_tokens(int(row["brief_chars"]))
    stack_tokens = first_turn.est_tokens(len(stack)) if stack is not None else None
    delivery_tokens = int(delivery["est_tokens"]) if delivery else 0
    # Without the bound delivery, ours is only the agent's own stack: a part, not the whole. Then ours and the harness
    # remainder (which would swallow the undelivered context) stay unknown rather than misattributed.
    ours = (stack_tokens or 0) + delivery_tokens if delivery else None
    parts: dict[str, Any] = {
        "total": first_turn._part(total, "exact"), "brief": first_turn._part(brief, "estimate"), "ours": first_turn._part(ours, "estimate"),
    }
    if ours is None or brief is None:
        parts["harness"] = first_turn._part(None, "derived")
    else:
        parts["harness"] = first_turn._part(max(total - ours - brief, 0), "derived")
    for name in first_turn.HARNESS_PART_NAMES:
        parts[name] = first_turn._part(None, "ratio")
    scopes = first_turn.split_scope_tokens(delivery.get("blocks") or [], delivery_tokens) if delivery else {}
    parts["ah_global"] = first_turn._part(scopes.get("ah_global") if delivery else None, "estimate")
    parts["ah_project"] = first_turn._part(scopes.get("ah_project") if delivery else None, "estimate")
    role_tokens = None if stack_tokens is None else stack_tokens + scopes.get("ah_role", 0)
    parts["ah_role"] = first_turn._part(role_tokens, "estimate")
    parts["stack_basis"] = stack_basis
    parts["chars"] = {"brief": int(row.get("brief_chars") or 0), "stack": len(stack or ""), "delivery": "bound" if delivery else "none"}
    return parts


def stack_fingerprint(stack: str | None) -> str | None:
    return hashlib.sha256(stack.encode()).hexdigest()[:16] if stack else None
