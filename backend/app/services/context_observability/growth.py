"""Per-session peak context and compaction count, read from usage_calls. No new capture.

Context of a call is everything sent to the model: uncached input + cache reads + cache writes (the same sum for
Claude and Codex rows). A compaction is a call whose context fell to under COMPACTION_RATIO of the previous call's in
the same chain (session, sub-agent, model), where the previous one was at least COMPACTION_MIN_TOKENS. Splitting by
model keeps a side call on another model (Claude's title or summary calls) from reading as a compaction.
Sessions with no usage_calls rows (Pi, Agent Hub agents) stay NULL: unknown, not zero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

COMPACTION_RATIO = 0.5
COMPACTION_MIN_TOKENS = 30_000

_CALLS = """
    SELECT provider, session_id, agent_id,
           input_tokens + cached_input_tokens + cache_write_tokens AS ctx,
           lag(input_tokens + cached_input_tokens + cache_write_tokens)
               OVER (PARTITION BY provider, session_id, agent_id, model ORDER BY occurred_at, id) AS prev
    FROM usage_calls WHERE {scope}
"""
_AGGREGATE = """
    SELECT provider, session_id, agent_id, max(ctx) AS peak,
           count(*) FILTER (WHERE prev >= :min_tokens AND ctx < prev * CAST(:ratio AS float8)) AS compactions
    FROM calls GROUP BY provider, session_id, agent_id
"""
_UPDATE = (
    "WITH calls AS (" + _CALLS + ") UPDATE usage_sessions u SET peak_context_tokens = a.peak, compaction_count = a.compactions "
    "FROM (" + _AGGREGATE + ") a WHERE u.provider = a.provider AND u.session_id = a.session_id AND u.agent_id = a.agent_id "
    "AND (u.peak_context_tokens IS DISTINCT FROM a.peak OR u.compaction_count IS DISTINCT FROM a.compactions)"
)
_PARAMS = {"min_tokens": COMPACTION_MIN_TOKENS, "ratio": COMPACTION_RATIO}


async def update_since(db: AsyncSession, since: datetime) -> int:
    """Recompute the numbers for every session with activity since `since` (all of its calls count). Returns rows changed."""
    scope = "(provider, session_id) IN (SELECT provider, session_id FROM usage_sessions WHERE last_at >= :since)"
    result = await db.execute(text(_UPDATE.replace("{scope}", scope)), {**_PARAMS, "since": since})
    return int(getattr(result, "rowcount", 0) or 0)


async def update_sessions(db: AsyncSession, keys: list[tuple[str, str]]) -> int:
    """Recompute the numbers for the given (provider, root session id) pairs."""
    if not keys:
        return 0
    scope = "(provider, session_id) IN (SELECT * FROM unnest(CAST(:providers AS text[]), CAST(:sessions AS text[])))"
    params: dict[str, Any] = {**_PARAMS, "providers": [k[0] for k in keys], "sessions": [k[1] for k in keys]}
    result = await db.execute(text(_UPDATE.replace("{scope}", scope)), params)
    return int(getattr(result, "rowcount", 0) or 0)
