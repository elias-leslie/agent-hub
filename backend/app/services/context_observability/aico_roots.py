"""Measured context size per Aico root: what the model was sent on its latest response, for `st aico roots`.

A root is matched to its newest Agent Hub session by the links Agent Hub already records: the work role bound at launch
(`work_role.source` = `tether:root:<logicalSessionId>`) or the Aico session id (`aico-widget-<id>`) a Pi or Codex session carries.
The number is input + cache reads + cache writes of the newest main-chain call in usage_calls (Claude Code, Codex), else the
`input_tokens` of the newest response-scope usage event (Pi; its input already includes the cache). Nothing matched or
no usage yet: the key is left out, which callers read as unknown. Never 0.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent, UsageCall

ROOT_SOURCE_PREFIX = "tether:root:"
MAX_KEYS = 50


class RootContext(BaseModel):
    session_id: str
    context_tokens: int
    at: datetime


async def latest_context(db: AsyncSession, keys: list[str]) -> dict[str, RootContext]:
    """Per requested key (a root's logicalSessionId or an aico-widget id) the context of its newest matched session."""
    wanted = list(dict.fromkeys(k for k in keys if k))[:MAX_KEYS]
    if not wanted:
        return {}
    source = Session.provider_metadata["work_role"]["source"].as_string()
    aico = Session.provider_metadata["aico_session_id"].as_string()
    rows = (await db.execute(
        select(Session.id, source, aico, func.coalesce(Session.last_activity_at, Session.created_at))
        .where(Session.parent_session_id.is_(None),
               source.in_([ROOT_SOURCE_PREFIX + k for k in wanted]) | aico.in_(wanted))
    )).all()
    newest: dict[str, tuple[datetime, str]] = {}
    for session_id, src, aico_id, active in rows:
        for key in (src[len(ROOT_SOURCE_PREFIX):] if src else None, aico_id):
            if key in wanted and (key not in newest or active > newest[key][0]):
                newest[key] = (active, session_id)
    sessions = sorted({sid for _, sid in newest.values()})
    measured = await _measure(db, sessions)
    return {key: measured[sid] for key, (_, sid) in newest.items() if sid in measured}


async def _measure(db: AsyncSession, session_ids: list[str]) -> dict[str, RootContext]:
    if not session_ids:
        return {}
    out: dict[str, RootContext] = {}
    context = UsageCall.input_tokens + UsageCall.cached_input_tokens + UsageCall.cache_write_tokens
    calls = (await db.execute(
        select(UsageCall.session_id, context, UsageCall.occurred_at)
        .where(UsageCall.session_id.in_(session_ids), UsageCall.agent_id == "")
        .distinct(UsageCall.session_id)
        .order_by(UsageCall.session_id, UsageCall.occurred_at.desc(), UsageCall.id.desc())
    )).all()
    for session_id, tokens, at in calls:
        if tokens and tokens > 0:
            out[session_id] = RootContext(session_id=session_id, context_tokens=int(tokens), at=at)
    rest = [s for s in session_ids if s not in out]
    if rest:
        scope = SessionEvent.usage["scope"].as_string()
        tokens = SessionEvent.usage["input_tokens"].as_integer()
        events = (await db.execute(
            select(SessionEvent.session_id, tokens, SessionEvent.created_at)
            .where(SessionEvent.session_id.in_(rest), SessionEvent.event_type == "usage", scope == "response")
            .distinct(SessionEvent.session_id)
            .order_by(SessionEvent.session_id, SessionEvent.created_at.desc())
        )).all()
        for session_id, value, at in events:
            if value and value > 0:
                out[session_id] = RootContext(session_id=session_id, context_tokens=int(value), at=at)
    return out
