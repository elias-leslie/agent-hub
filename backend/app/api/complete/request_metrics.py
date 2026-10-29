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


def model_request_record(message: AssistantMessage) -> dict[str, Any] | None:
    """The compact record for one model request, or None when the message carries no metrics."""
    metrics = request_metrics_of(message)
    if metrics is None:
        return None
    record = {key: value for key, value in metrics.items() if value is not None and key != "retry_log"}
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
        await store_event(
            db, session_id, SessionEventType.TOOL_AUDIT, tool_name=MODEL_REQUEST_TOOL,
            content=json.dumps(record, sort_keys=True), tool_output=record,
            source_event_id=f"{source_prefix}:{index}:request" if source_prefix else None, **common,
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
