"""Read retained tool text and durations for session rows and sorting, without caps."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionEvent
from app.services.activity_accounting import returned_characters_expression
from app.services.context_accounting import context_split, tool_context_row
from app.services.session_efficiency import duration_split


def accounting_window(start: datetime | None, end: datetime | None, cursor: str | None):
    """Pin the exact interval across every sort's pagination cursor."""
    inner = cursor
    retained = None
    if cursor:
        try:
            data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if isinstance(data, dict) and data.get("v") == 2:
                retained = (datetime.fromisoformat(data["start"]), datetime.fromisoformat(data["end"]))
                inner = data["cursor"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("Invalid accounting cursor") from exc
    if (start is None) != (end is None):
        raise ValueError("Supply both accounting_start and accounting_end")
    if start is not None and end is not None and (start.tzinfo is None or end.tzinfo is None):
        raise ValueError("Accounting timestamps must include a timezone")
    if retained is not None:
        if start is not None and (start, end) != retained:
            raise ValueError("Session cursor does not match the accounting window")
        start, end = retained
    if end is None:
        end = datetime.now(UTC)
        start = end - timedelta(hours=24)
    assert start is not None
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Accounting timestamps must include a timezone")
    if start >= end or end > datetime.now(UTC):
        raise ValueError("Accounting window must be ordered and cannot end in the future")
    return start.astimezone(UTC), end.astimezone(UTC), inner


def accounting_cursor(cursor: str | None, start: datetime, end: datetime) -> str | None:
    if cursor is None:
        return None
    data = {"v": 2, "start": start.isoformat(), "end": end.isoformat(), "cursor": cursor}
    return base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")


def summarize_session_duration(events: list[Any], *, start: datetime, end: datetime) -> dict:
    from app.services.admin_activity_cost import (
        _occupancy,
        _tool_family,
        measured_tool_interval,
        paired_activity_tools,
    )

    tools, results, _ = paired_activity_tools(events)
    intervals = []
    context = []
    missing = 0
    for key, tool in tools.items():
        _, category = _tool_family(tool)
        context.append(tool_context_row(tool, results.get(key), category))
        interval = measured_tool_interval(tool, results.get(key), cutoff=start, now=end,
                                          session_type=getattr(tool, "session_type", None))
        if interval is None:
            missing += 1
        else:
            intervals.append((*interval, category))
    return duration_split(_occupancy(intervals), calls=len(tools), missing=missing, truncated=False) | {"context_split": context_split(context)}


async def fetch_session_accounting(db: AsyncSession, selected_ids: Any, *, start: datetime, end: datetime) -> dict[str, dict]:
    """Stream complete filtered session histories; cap neither sessions nor event rows.

    Memory holds one session at a time. The event boundaries, pairing, wrapper
    suppression and overlap union are identical to the Activity ledger.
    """
    event_time = func.coalesce(SessionEvent.source_timestamp, SessionEvent.created_at)
    query = select(
        SessionEvent.id, SessionEvent.session_id, SessionEvent.turn, SessionEvent.sequence,
        SessionEvent.event_type, SessionEvent.call_id, SessionEvent.tool_name, SessionEvent.tool_input,
        SessionEvent.duration_ms, SessionEvent.source_timestamp, SessionEvent.created_at, Session.session_type,
        returned_characters_expression(SessionEvent),
    ).join(Session, Session.id == SessionEvent.session_id).where(SessionEvent.session_id.in_(selected_ids), event_time >= start, event_time < end,
            SessionEvent.event_type.in_(["tool_use", "tool_result"]))
    query = query.order_by(SessionEvent.session_id, SessionEvent.turn, SessionEvent.sequence).execution_options(yield_per=1000)
    stream = await db.stream(query)
    output = {}
    sid = None
    events = []
    try:
        async for event in stream:
            if sid is not None and event.session_id != sid:
                output[sid] = await asyncio.to_thread(summarize_session_duration, events, start=start, end=end)
                events = []
            sid = event.session_id
            events.append(event)
        if sid is not None:
            output[sid] = await asyncio.to_thread(summarize_session_duration, events, start=start, end=end)
    finally:
        await stream.close()
    return output


def accounting_sort_key(sid: str, accounting: dict, field: str, direction: str) -> tuple:
    context = accounting.get("context_split") or {}
    if field == "admin_share":
        value = context.get("admin_share")
    elif field == "admin_tokens":
        value = context.get("admin_tokens_estimate") if context.get("admin_share") is not None else None
    else:
        value = accounting["admin_seconds"] if accounting["admin_share"] is not None else None
    return value is None, -value if value is not None and direction == "desc" else value or 0, sid
