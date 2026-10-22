"""Bounded, content-free comparison of source-backed native turn outcomes."""

import asyncio
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SessionEvent

_SETTINGS = ("requested_model", "reasoning_effort", "service_tier", "cyber_access_program", "approval_policy")


def summarize_native_turns(rows: list[dict], *, limit: int) -> dict[str, Any]:
    turns: dict[str, dict] = {}
    for row in rows:
        facts = row.get("tool_output") or {}
        usage = row.get("usage") or {}
        turn_id = facts.get("native_turn_id") or facts.get("turn_id") or usage.get("turn_id")
        if not isinstance(turn_id, str) or not row.get("source_event_id"):
            continue
        turn = turns.setdefault(turn_id, {
            "native_turn_id": turn_id, "status": "unknown", "native_category": None,
            "settings": {}, "event_ids": [], "response_tokens": 0,
            "started_at": None, "terminal_at": None,
        })
        turn["event_ids"].append(str(row["id"]))
        timestamp = row.get("source_timestamp")
        if row["event_type"] == "native_settings":
            turn["settings"].update({key: facts[key] for key in _SETTINGS if key in facts})
        elif row["event_type"] == "native_lifecycle":
            status = facts.get("status")
            if status == "started":
                turn["started_at"] = timestamp
            elif status in {"completed", "failed", "aborted"}:
                turn.update(status=status, terminal_at=timestamp)
            if isinstance(facts.get("native_category"), str):
                turn["native_category"] = facts["native_category"]
        elif row["event_type"] == "error" and isinstance(facts.get("codex_error_info"), str):
            turn.update(status="failed", native_category=facts["codex_error_info"], terminal_at=timestamp)
        elif row["event_type"] == "usage" and usage.get("scope") == "response":
            turn["response_tokens"] += sum(
                value for key in ("input_tokens", "output_tokens")
                if isinstance((value := usage.get(key)), int) and not isinstance(value, bool) and value >= 0
            )

    # Native completion is a transport outcome, never proof of useful work or
    # a claim about the provider's private classifier.
    ordered = sorted(
        (turn for turn in turns.values() if turn["status"] != "unknown"),
        key=lambda turn: str(turn["terminal_at"] or turn["started_at"] or ""),
    )
    counts = Counter(turn["native_category"] or turn["status"] for turn in ordered)
    selected = ordered[-limit:]
    for turn in selected:
        position = ordered.index(turn)
        neighbors = ordered[max(0, position - 1):position] + ordered[position + 1:position + 2]
        turn["nearby_turns"] = [{
            "native_turn_id": other["native_turn_id"], "status": other["status"],
            "native_category": other["native_category"],
            "observed_setting_differences": {
                key: {"this_turn": turn["settings"].get(key), "nearby_turn": other["settings"].get(key)}
                for key in _SETTINGS
                if turn["settings"].get(key) != other["settings"].get(key)
            },
        } for other in neighbors]
        turn["observation_confidence"] = "confirmed"
        turn["classifier_cause"] = "unknown"
    denominator = len(ordered)
    return {
        "denominator": denominator,
        "denominator_basis": "source-backed terminal native turns in the retrieved event window",
        "categories": [{"category": key, "turns": value, "rate": value / denominator} for key, value in sorted(counts.items())],
        "turns": selected,
        "uncompleted_turns": len(turns) - denominator,
    }


async def native_turn_diagnostics(
    db: AsyncSession, session_id: str, *, limit: int, event_limit: int,
    managed_transcript: str | None = None,
) -> dict:
    if managed_transcript is not None:
        # Managed command positions belong to their existing native authority.
        # Compare the registered source directly instead of creating another
        # lifecycle projection or reporting failure-only event denominators.
        from app.services.session_ingestion.adapters.transcript_parsers import (
            inspect_transcript_source,
            read_incremental_transcript_events,
        )

        events, checkpoint = await asyncio.to_thread(read_incremental_transcript_events, managed_transcript)
        health = await asyncio.to_thread(inspect_transcript_source, managed_transcript, checkpoint)
        rows = [{"id": event.source_event_id, "event_type": event.event_type,
                 "source_event_id": event.source_event_id, "source_timestamp": event.source_timestamp,
                 "tool_output": event.tool_output, "usage": event.usage}
                for event in events if event.event_type in {"native_lifecycle", "native_settings", "error", "usage"}]
        truncated = len(rows) > event_limit
        return {"session_id": session_id, "source": "registered_native_transcript",
                "source_health": health.model_dump(mode="json"), "events_truncated": truncated,
                **summarize_native_turns(rows[-event_limit:], limit=limit)}
    result = await db.execute(select(
        SessionEvent.id, SessionEvent.event_type, SessionEvent.source_event_id,
        SessionEvent.source_timestamp, SessionEvent.tool_output, SessionEvent.usage,
    ).where(
        SessionEvent.session_id == session_id,
        SessionEvent.event_type.in_(["native_lifecycle", "native_settings", "error", "usage"]),
    ).order_by(SessionEvent.source_timestamp.desc().nulls_last(), SessionEvent.created_at.desc(), SessionEvent.id.desc()).limit(event_limit + 1))
    rows = list(result.mappings())
    truncated = len(rows) > event_limit
    rows = list(reversed(rows[:event_limit]))
    return {"session_id": session_id, "source": "session_events", "events_truncated": truncated, **summarize_native_turns(rows, limit=limit)}
