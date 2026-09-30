"""Native model evidence state carried by the JSONL parser checkpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.session_ingestion.models import SessionModelEvidence


def _text(value: object, limit: int = 512) -> str | None:
    return value if isinstance(value, str) and value.strip() and len(value) <= limit else None


def _timestamp(value: object) -> datetime | None:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
        return result if result is not None and result.tzinfo is not None else None
    except ValueError:
        return None


def observe_model_record(
    state: dict[str, Any], obj: dict[str, object], line: int,
) -> None:
    """Ignore copied context and retain only current-turn native evidence."""
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return
    kind = obj.get("type")
    timestamp = _timestamp(obj.get("timestamp"))
    if kind == "session_meta":
        if state.get("session_id"):
            return  # A child's copied parent header cannot replace its identity.
        session_id = _text(payload.get("id"))
        if not session_id:
            return
        spawn: Any = payload.get("source")
        spawn = spawn.get("subagent") if isinstance(spawn, dict) else None
        spawn = spawn.get("thread_spawn") if isinstance(spawn, dict) else None
        spawn = spawn if isinstance(spawn, dict) else {}
        native_session_id = _text(payload.get("session_id")) or session_id
        state.update(
            session_id=session_id, native_thread_id=session_id, transcript_runtime_session_id=native_session_id, native_session_id=native_session_id,
            parent_thread_id=_text(payload.get("parent_thread_id")) or _text(spawn.get("parent_thread_id")),
            started_at=timestamp.isoformat() if timestamp else None,
            history_start_ordinal=payload.get("subagent_history_start_ordinal"),
            local_started=False,
            evidence=SessionModelEvidence(
                session_id=session_id, native_thread_id=session_id, transcript_runtime_session_id=native_session_id, native_session_id=native_session_id,
            ).model_dump(mode="json"),
        )
        return
    session_id = state.get("session_id")
    if not session_id:
        return
    attributed_thread = _text(payload.get("thread_id"))
    if attributed_thread is not None and attributed_thread != session_id:
        return
    attributed_session = _text(payload.get("session_id"))
    expected_session = state.get("native_session_id") or session_id
    if attributed_session is not None and attributed_session != expected_session:
        return
    start = state.get("history_start_ordinal")
    ordinal = obj.get("ordinal")
    ordinal_local = isinstance(start, int) and isinstance(ordinal, int) and ordinal >= start
    if isinstance(start, int) and isinstance(ordinal, int) and ordinal < start:
        return
    cutoff = _timestamp(state.get("started_at"))
    if (
        state.get("parent_thread_id") and attributed_thread != session_id and not ordinal_local
        and (timestamp is None or cutoff is None or timestamp < cutoff)
    ):
        return
    if kind == "event_msg" and payload.get("type") == "task_started":
        state["local_started"] = True
        state["task_turn_id"] = _text(payload.get("turn_id"))
        state["evidence"] = SessionModelEvidence(
            session_id=session_id, native_thread_id=session_id, transcript_runtime_session_id=state.get("native_session_id"), native_session_id=state.get("native_session_id"),
            turn_id=state["task_turn_id"], source_line=line, source_timestamp=timestamp,
        ).model_dump(mode="json")
        return
    if state.get("parent_thread_id") and not (
        state.get("local_started") or attributed_thread == session_id or ordinal_local
    ):
        return
    turn_id = _text(payload.get("turn_id"))
    if kind == "turn_context":
        active_turn = state.get("task_turn_id")
        if active_turn and turn_id != active_turn:
            return
        state["evidence"] = SessionModelEvidence(
            session_id=session_id, native_thread_id=session_id, transcript_runtime_session_id=state.get("native_session_id"), native_session_id=state.get("native_session_id"),
            turn_id=turn_id, source_line=line, source_timestamp=timestamp,
            requested_model=_text(payload.get("model")),
            requested_reasoning_effort=_text(payload.get("effort"), 64),
        ).model_dump(mode="json")
        return
    evidence = state.get("evidence")
    if not isinstance(evidence, dict) or not evidence.get("turn_id"):
        return
    if turn_id is not None and turn_id != evidence["turn_id"]:
        return
    if state.get("task_turn_id") and state["task_turn_id"] != evidence["turn_id"]:
        return
    context_timestamp = _timestamp(evidence.get("source_timestamp"))
    if timestamp is None or context_timestamp is None or timestamp < context_timestamp:
        return
    if kind == "response_item" and (
        payload.get("type") == "reasoning"
        or (payload.get("type") == "message" and payload.get("role") == "assistant")
    ):
        source = "codex.response_item.model"
    elif kind == "token_usage_record":
        source = "codex.token_usage_record.model"
    else:
        return
    model = _text(payload.get("model"))
    if model:
        observed_models = state.setdefault("observed_models", [])
        if model not in observed_models:
            observed_models.append(model)
        evidence.update(
            observed_model=model, observed_source=source, observed_source_line=line,
            observed_source_timestamp=timestamp.isoformat() if timestamp else None,
        )
