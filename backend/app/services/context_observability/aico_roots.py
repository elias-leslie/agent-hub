"""Measured context size per Aico root: what the model was sent on its latest response, for `st aico roots`.

A root is matched to its own Agent Hub session by the root's native harness session id when the caller sends it (Agent Hub
keys a Claude Code or Codex session by that id, so the key is the Agent Hub session id itself). Without it, by the links Agent
Hub already records: the work role bound at launch (`work_role.source` = `tether:root:<logicalSessionId>`) or the Aico session
id (`aico-widget-<id>`) a Pi or Codex session carries; the `claude -p` / `codex exec` processes a root starts inherit that
source and are top-level too, so sessions created while an earlier one of the same source was still active are left out.
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
MAX_KEYS = 300  # 3 keys per root (logical id, widget id, native session id): 100 roots


class RootContext(BaseModel):
    session_id: str
    context_tokens: int
    at: datetime


async def latest_context(db: AsyncSession, keys: list[str]) -> dict[str, RootContext]:
    """Per requested key the context of its matched session: a key is a root's logicalSessionId or an aico-widget id
    (its newest matched session), or a native harness session id (that Agent Hub session)."""
    wanted = list(dict.fromkeys(k for k in keys if k))[:MAX_KEYS]
    if not wanted:
        return {}
    source = Session.provider_metadata["work_role"]["source"].as_string()
    aico = Session.provider_metadata["aico_session_id"].as_string()
    rows = (await db.execute(
        select(Session.id, source, aico, Session.created_at, func.coalesce(Session.last_activity_at, Session.created_at),
               Session.status)
        .where(Session.parent_session_id.is_(None),
               source.in_([ROOT_SOURCE_PREFIX + k for k in wanted]) | aico.in_(wanted) | Session.id.in_(wanted))
        .order_by(Session.created_at, Session.id)
    )).all()
    newest: dict[str, tuple[datetime, str]] = {}
    chains: dict[str, list[tuple[str, datetime, datetime, bool]]] = {}
    for session_id, src, aico_id, created, active, status in rows:
        if session_id in wanted:  # the root's own native session: exact, whatever else shares its source
            newest[session_id] = (active, session_id)
        for key in (src[len(ROOT_SOURCE_PREFIX):] if src else None, aico_id):
            if key in wanted:
                chains.setdefault(key, []).append((session_id, created, active, status == "active"))
    for key, sessions in chains.items():
        chosen = _own_sessions(sessions)
        newest[key] = max(((active, sid) for sid, _, active in chosen), key=lambda item: item[0])
    sessions = sorted({sid for _, sid in newest.values()})
    measured = await _measure(db, sessions)
    return {key: measured[sid] for key, (_, sid) in newest.items() if sid in measured}


def _own_sessions(sessions: list[tuple[str, datetime, datetime, bool]]) -> list[tuple[str, datetime, datetime]]:
    """The sessions of one source in creation order without the ones started while an earlier kept one was still active:
    those are the `claude -p` / `codex exec` processes the root launched, which inherit its source. A session is still
    active until its last activity, or for as long as Agent Hub holds it active."""
    kept: list[tuple[str, datetime, datetime]] = []
    busy_until: datetime | None = None
    holding = False
    for session_id, created, active, is_active in sessions:
        if kept and (holding or (busy_until is not None and created <= busy_until)):
            continue
        kept.append((session_id, created, active))
        busy_until = active if busy_until is None else max(busy_until, active)
        holding = holding or is_active
    return kept


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
            .order_by(SessionEvent.session_id, SessionEvent.created_at.desc(), SessionEvent.turn.desc(),
                      SessionEvent.sequence.desc(), SessionEvent.id.desc())
        )).all()
        for session_id, value, at in events:
            if value and value > 0:
                out[session_id] = RootContext(session_id=session_id, context_tokens=int(value), at=at)
    return out
