"""Shared announce-back helper for orchestration endpoints.

When a parent_session_id is provided, stores subagent results as events
in the parent session so the session timeline includes orchestration output.
"""

from __future__ import annotations

import logging
import time

from app.services.orchestration.subagent_models import SubagentResult

logger = logging.getLogger(__name__)


async def announce_results_to_session(
    parent_session_id: str,
    results: list[SubagentResult],
) -> None:
    """Store subagent results as events in the parent session (fire-and-forget)."""
    try:
        from app.db import async_session
        from app.services.event_storage import store_subagent_result_event

        async with async_session() as db:
            for result in results:
                duration_ms = None
                if result.started_at and result.completed_at:
                    duration_ms = int(
                        (result.completed_at - result.started_at).total_seconds() * 1000
                    )
                await store_subagent_result_event(
                    db=db,
                    session_id=parent_session_id,
                    subagent_id=result.subagent_id,
                    subagent_name=result.name,
                    content=result.content,
                    status=result.status,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    model_used=result.model,
                    duration_ms=duration_ms,
                )
            await db.commit()
            logger.info(
                f"Announced {len(results)} subagent result(s) to session {parent_session_id}"
            )
    except Exception as e:
        logger.error(f"Failed to announce results to session {parent_session_id}: {e}")
