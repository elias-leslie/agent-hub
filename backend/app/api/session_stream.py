"""Reattach to a session's turn: ``GET /sessions/{id}/stream``.

A chat turn is owned by the server (``app.services.turn_runs``), so any client can pick it up again from the
last ``seq`` it saw: the events after it are replayed, then the stream follows live until the turn ends. Every
subscriber gets the same bytes the starting request got.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.session_queries import get_session_or_404
from app.services.turn_runs import (
    DONE_CHUNK,
    TURN_KEY,
    TurnLogGap,
    interrupted_error_event,
    registry,
    sse_event,
)

router = APIRouter()

_STREAM_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


def _persisted_turn(provider_metadata: Any) -> dict[str, Any]:
    turn = provider_metadata.get(TURN_KEY) if isinstance(provider_metadata, dict) else None
    return turn if isinstance(turn, dict) else {}


async def _last_state(session_id: str, turn: dict[str, Any], after_seq: int) -> AsyncIterator[str]:
    """No turn is running in this process: say how the last one ended, once."""
    state = turn.get("state")
    if state in ("interrupted", "running"):  # "running" with no live task is a turn this process never started
        yield interrupted_error_event(session_id, after_seq + 1)
    else:
        yield sse_event(
            {
                "type": "idle",
                "session_id": session_id,
                "last_state": state or "none",
                "turn_id": turn.get("turn_id"),
                "ended_at": turn.get("ended_at"),
            }
        )
    yield DONE_CHUNK


@router.get("/sessions/{session_id}/stream")
async def stream_session_turn(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    after_seq: Annotated[int, Query(ge=0, description="Replay events with seq greater than this")] = 0,
    turn_id: Annotated[str | None, Query(description="Refuse if the session's turn is a different one")] = None,
) -> StreamingResponse:
    """Replay a session's turn from ``after_seq``, then follow it live until it ends (SSE).

    With no turn running, the log of the last turn is replayed if this process still holds it; otherwise one
    ``idle`` event (or, for a turn cut off by a restart, one ``error`` event) states how it ended.
    """
    try:
        session = await get_session_or_404(db, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    persisted = _persisted_turn(session.provider_metadata)
    await db.rollback()  # the stream below can last the whole turn; do not hold a connection for it

    run = registry.get(session_id)
    if run is None:
        body: AsyncIterator[str] = _last_state(session_id, persisted, after_seq)
    else:
        if turn_id and turn_id != run.turn_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "turn_mismatch",
                    "message": "The session's turn is a different one than the turn_id asked for.",
                    "details": {"session_id": session_id, "turn_id": run.turn_id},
                },
            )
        try:
            run.events_after(after_seq)
        except TurnLogGap as exc:
            raise HTTPException(
                status_code=410,
                detail={
                    "error": "turn_log_gap",
                    "message": str(exc),
                    "details": {"session_id": session_id, "oldest_seq": exc.oldest_seq},
                },
            ) from exc
        body = run.follow(after_seq)
    return StreamingResponse(body, media_type="text/event-stream", headers=_STREAM_HEADERS)
