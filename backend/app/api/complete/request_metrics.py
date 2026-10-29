"""Persist each model request's liveness record and its retries as session events.

The provider and ``tool_loop.run_turn`` record a compact ``request_metrics`` diagnostic on every turn's final
message (longest silence between frames, keepalives, longest tool-argument stream, retries, outcome). This turns
it into the same events the workflow path writes: an ``error`` event ``turn_retry: <reason>`` per re-send and one
``tool_audit`` event named ``model_request``, so a slow run can be told from a dead one afterwards.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.types import AssistantMessage
from app.llm.utils.request_metrics import request_metrics_of
from app.models import SessionEventType
from app.services.event_storage import store_event

logger = logging.getLogger(__name__)

MODEL_REQUEST_TOOL = "model_request"
# Parts of a request's metrics that are stored as events of their own, not inside the ``model_request`` audit event.
_SEPARATE_RECORDS = ("retry_log", "compactions")


def model_request_record(message: AssistantMessage) -> dict[str, Any] | None:
    """The compact record for one model request, or None when the message carries no metrics."""
    metrics = request_metrics_of(message)
    if metrics is None:
        return None
    record = {key: value for key, value in metrics.items() if value is not None and key not in _SEPARATE_RECORDS}
    record["model"] = message.model
    record["stop_reason"] = message.stop_reason
    return record


async def store_model_requests(
    db: AsyncSession,
    session_id: str,
    messages: Iterable[AssistantMessage],
    *,
    model_used: str | None,
    agent_id: str | None,
    source_prefix: str | None = None,
) -> None:
    """Add the retry and ``model_request`` events for ``messages``; the caller commits.

    ``source_prefix`` gives each event a stable source identity (``<prefix>:<message index>:...``), for a writer that
    may save the same messages again and must not duplicate them (a workflow attempt saved turn by turn).
    """
    for index, message in enumerate(messages):
        record = model_request_record(message)
        if record is None:
            continue
        common: dict[str, Any] = {"model_used": model_used, "agent_id": agent_id, "agent_name": agent_id}
        for number, retry in enumerate((request_metrics_of(message) or {}).get("retry_log") or []):
            await store_event(
                db, session_id, SessionEventType.ERROR, content=f"turn_retry: {retry.get('reason', 'interrupted')}",
                tool_output=retry, source_event_id=f"{source_prefix}:{index}:retry:{number}" if source_prefix else None,
                **common,
            )
        for number, compaction in enumerate((request_metrics_of(message) or {}).get("compactions") or []):
            await store_compaction(
                db, session_id, compaction, agent_id=agent_id,
                source_event_id=f"{source_prefix}:{index}:compaction:{number}" if source_prefix else None,
            )
        await store_event(
            db, session_id, SessionEventType.TOOL_AUDIT, tool_name=MODEL_REQUEST_TOOL,
            content=json.dumps(record, sort_keys=True), tool_output=record,
            source_event_id=f"{source_prefix}:{index}:request" if source_prefix else None, **common,
        )


def compaction_text(compaction: dict[str, Any]) -> str:
    """The one line a session log shows for a compaction."""
    if compaction.get("status") != "ok":
        return f"Context compaction failed: {compaction.get('error')}"
    return (
        f"Context compacted: {compaction.get('tokens_before')} -> {compaction.get('tokens_after')} tokens "
        f"({compaction.get('messages_summarized')} messages summarized by {compaction.get('summarizer_model')})"
    )


async def store_compaction(
    db: AsyncSession, session_id: str, compaction: dict[str, Any], *, agent_id: str | None,
    source_event_id: str | None = None,
) -> None:
    """Save one compaction as a ``compaction`` event and charge the summarizer's tokens to the session.

    The session's original events are untouched: a compaction changes what the model was sent, not the record.
    """
    from app.services.context_tracker import log_token_usage

    ok = compaction.get("status") == "ok"
    model = compaction.get("summarizer_model")
    usage = {
        "input_tokens": compaction.get("input_tokens", 0),
        "output_tokens": compaction.get("output_tokens", 0),
        "cache_read_tokens": compaction.get("cache_read_tokens", 0),
        "cache_write_tokens": compaction.get("cache_write_tokens", 0),
        "cost_usd": compaction.get("cost_usd", 0.0),
    }
    await store_event(
        db, session_id, SessionEventType.COMPACTION, content=compaction_text(compaction),
        tool_output=compaction, model_used=model, agent_id=agent_id, agent_name=agent_id,
        usage=usage if ok else None, source_event_id=source_event_id,
    )
    if ok and model and (usage["input_tokens"] or usage["output_tokens"]):
        await log_token_usage(
            db, session_id, model, usage["input_tokens"], usage["output_tokens"], usage["cost_usd"],
            cache_read_tokens=usage["cache_read_tokens"], cache_write_tokens=usage["cache_write_tokens"],
        )


async def persist_failed_requests(
    db: AsyncSession | None,
    session_id: str | None,
    result: Any,
    model_used: str | None,
    agent_id: str | None,
) -> None:
    """Keep a failed completion's request records: the error response rolls the request's transaction back."""
    if db is None or not session_id or session_id.startswith("ephemeral:"):
        return
    try:
        await store_model_requests(
            db, session_id, getattr(result, "usage_messages", None) or [result.message],
            model_used=model_used, agent_id=agent_id,
        )
        await db.commit()
    except Exception as exc:
        logger.warning("Could not persist request metrics for failed completion %s: %s", session_id, exc)
        await db.rollback()
