"""The transcript an Agent Hub step leaves on its attempt's child session.

The tool loop runs with no database open (the engine holds no transaction across an executor), so afterwards this
writes what happened as ordinary ``session_events`` on the attempt session the engine already created: the input,
then per model turn the thinking, answer, tool calls and their results, with the served model and token usage on
each turn, and typed provider outcomes. Per-call ``cost_logs`` rows are written the way a normal completion does.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.types import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
)
from app.llm.utils.request_metrics import request_metrics_of
from app.models import SessionEventType
from app.services.context_tracker import log_token_usage
from app.services.event_storage import lock_session_event_ingestion, store_event, storing_history
from app.services.token_counter import estimate_usage_cost

from .executor_common import Usage, clip

logger = logging.getLogger(__name__)

TOOL_RESULT_CHARS = 4000


@dataclass
class Transcript:
    """What one tool-loop run did, in the order it happened."""

    session_id: str
    agent_slug: str | None
    requested_model: str
    input_messages: Sequence[Mapping[str, Any]] = ()
    turns: Sequence[AssistantMessage] = ()
    tool_results: Mapping[str, ToolResultMessage] = field(default_factory=dict)
    # (number of turns finished before the retry, reason): a turn re-run after an interrupted stream.
    retries: Sequence[tuple[int, str]] = ()
    error: str | None = None


def usage_payload(message: AssistantMessage, requested_model: str) -> dict[str, Any]:
    """Per-turn usage as the session UI reads it, with the model that answered and any typed outcome."""

    # Imported here: app.api's package init imports the workflow routes, which import the engine and its executors.
    from app.api.complete.runtime_usage import outcome_usage, served_model

    counts = Usage()
    usage = message.usage
    counts.add(usage.input, usage.cache_read, usage.cache_write, usage.output, usage.reasoning)
    payload: dict[str, Any] = {
        **counts.as_dict(),
        "cost_usd": usage.cost.total,
        "stop_reason": message.stop_reason,
        "requested_model": requested_model,
        "served_model": served_model(message, requested_model),
    }
    return {**payload, **(outcome_usage(message) or {})}


def _text(result: ToolResultMessage) -> str:
    return "\n".join(b.text for b in result.content if isinstance(b, TextContent) and b.text)


async def record_transcript(db: AsyncSession, transcript: Transcript) -> None:
    """Write the transcript as session events and cost rows; the caller commits.

    History, not activity (as for a native transcript): nothing is touched on the attempt session and nothing is copied
    onto the run session. That also keeps this write off the run's row and event-ingestion locks, which the engine takes
    in the other order when it settles a step, so two steps finishing together cannot deadlock.
    """

    with storing_history():
        await _write_events(db, transcript)


async def _write_events(db: AsyncSession, transcript: Transcript) -> None:
    # Imported here: app.api's package init imports the workflow routes, which import the engine and its executors.
    from app.api.complete.helpers import normalize_content_for_storage
    from app.api.complete.request_metrics import store_model_requests
    from app.api.complete.runtime_usage import accounting_model, outcome_usage, served_model

    sid, agent = transcript.session_id, transcript.agent_slug
    await lock_session_event_ingestion(db, sid)
    for item in transcript.input_messages:
        role = item.get("role")
        if role not in ("system", "user"):
            continue
        await store_event(
            db, sid,
            SessionEventType.SYSTEM_MESSAGE if role == "system" else SessionEventType.USER_MESSAGE,
            role=role, content=normalize_content_for_storage(item.get("content")),
            agent_id=agent, agent_name=agent,
        )
    for index, message in enumerate(transcript.turns):
        model = served_model(message, transcript.requested_model)
        # The turn's re-sends and its liveness record (longest silence, keepalives, tool-argument size, outcome), the
        # same events a /complete request saves. A turn that carries no record still gets its re-sends from the loop.
        if request_metrics_of(message) is not None:
            await store_model_requests(db, sid, [message], model_used=model, agent_id=agent)
        else:
            for after, reason in transcript.retries:
                if after == index:
                    await store_event(
                        db, sid, SessionEventType.ERROR, content=f"turn_retry: {reason}",
                        agent_id=agent, agent_name=agent, model_used=transcript.requested_model,
                    )
        usage: dict[str, Any] | None = usage_payload(message, transcript.requested_model)

        def lead() -> dict[str, Any] | None:
            """The turn's usage rides on the first event it writes, so it is counted once."""
            nonlocal usage
            taken, usage = usage, None
            return taken

        thinking = "\n".join(b.thinking for b in message.content if isinstance(b, ThinkingContent) and b.thinking)
        text = "\n".join(b.text for b in message.content if isinstance(b, TextContent) and b.text)
        calls = [b for b in message.content if isinstance(b, ToolCall)]
        common: dict[str, Any] = {"model_used": model, "agent_id": agent, "agent_name": agent}
        if thinking:
            await store_event(
                db, sid, SessionEventType.THINKING, content=thinking,
                tokens=message.usage.reasoning or None, usage=lead(), **common,
            )
        failed = message.stop_reason in ("error", "aborted")
        if text or not (calls or failed):
            await store_event(
                db, sid, SessionEventType.ASSISTANT_MESSAGE, role="assistant", content=text,
                tokens=message.usage.output, usage=lead(), **common,
            )
        for call in calls:
            await store_event(
                db, sid, SessionEventType.TOOL_USE, tool_name=call.name, call_id=call.id,
                tool_input=dict(call.arguments or {}), usage=lead(), **common,
            )
            result = transcript.tool_results.get(call.id)
            if result is not None:
                body = clip(_text(result), TOOL_RESULT_CHARS)
                await store_event(
                    db, sid, SessionEventType.TOOL_RESULT, tool_name=call.name, call_id=call.id,
                    content=body, tool_output={"content": body, "is_error": result.is_error}, **common,
                )
        if failed:
            await store_event(
                db, sid, SessionEventType.ERROR,
                content=f"{message.stop_reason}: {message.error_message or 'provider ended the turn'}",
                usage=lead() or outcome_usage(message), **common,
            )
        accounted = accounting_model(message, transcript.requested_model)
        cost = estimate_usage_cost(
            message.usage.input, message.usage.output, accounted,
            cache_read_tokens=message.usage.cache_read, cache_write_tokens=message.usage.cache_write,
        )
        await log_token_usage(
            db, sid, accounted, message.usage.input, message.usage.output, cost.total_cost_usd,
            cache_read_tokens=message.usage.cache_read, cache_write_tokens=message.usage.cache_write,
        )
    if transcript.error:
        await store_event(
            db, sid, SessionEventType.ERROR, content=transcript.error,
            agent_id=agent, agent_name=agent, model_used=transcript.requested_model,
        )


async def persist_transcript(transcript: Transcript) -> None:
    """Managed-session wrapper: one short transaction after the loop has finished."""

    from app.db import async_session

    async with async_session() as db:
        await record_transcript(db, transcript)
        await db.commit()
