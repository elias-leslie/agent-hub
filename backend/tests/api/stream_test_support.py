"""Shared helpers for tests that drive the streaming done step.

``streaming._persist_and_build_done_sse`` saves messages, tracks citations,
closes one-shot sessions, writes the cost log row and records project cost.
Tests that reach it use :func:`patched_done_persistence` so a new side effect
needs one new patch here instead of one per test file.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.complete.streaming_context import StreamContext
from app.constants.models import CLAUDE_SONNET


def make_stream_ctx(
    session_id: str,
    *,
    model: str = CLAUDE_SONNET,
    agent_used: str | None = None,
) -> StreamContext:
    """Build a StreamContext for an existing, non-one-shot Claude session."""
    return StreamContext(
        session_id=session_id,
        model=model,
        provider="claude",
        agent_used=agent_used,
        model_used=None,
        fallback_used=False,
        user_messages=None,
        stream_start=0.0,
        is_new_session=False,
        is_one_shot=False,
    )


@contextmanager
def patched_done_persistence(*, log_cost: bool = True) -> Iterator[SimpleNamespace]:
    """Replace the DB-backed side effects of the stream done step with AsyncMocks.

    Pass ``log_cost=False`` to keep the real ``_log_stream_cost`` (for tests that
    patch the cost-log database themselves). Yields the mocks by target name.
    """
    targets = {
        "save_messages_to_db": "app.api.complete.streaming_persistence.save_messages_to_db",
        "track_citations": "app.api.complete.streaming_persistence._track_citations",
        "close_one_shot_session": "app.api.complete.streaming_persistence.close_one_shot_session",
        "record_project_cost": "app.services.project_budget.record_project_cost",
    }
    if log_cost:
        targets["log_stream_cost"] = "app.api.complete.streaming._log_stream_cost"
    with ExitStack() as stack:
        mocks = {
            name: stack.enter_context(patch(target, new=AsyncMock()))
            for name, target in targets.items()
        }
        yield SimpleNamespace(**mocks)
