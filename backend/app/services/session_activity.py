"""Helpers for reasoning about session activity timestamps."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement

from app.models import Session, SessionEvent


def last_activity_expr() -> ColumnElement:
    """Return a SQL expression for the most recent observed session activity.

    Session rows are not updated on every SessionEvent insert, so cleanup logic
    must consider event timestamps directly or it will miss stuck sessions.
    """
    latest_event_at = (
        select(func.max(SessionEvent.created_at))
        .where(SessionEvent.session_id == Session.id)
        .correlate(Session)
        .scalar_subquery()
    )
    return func.coalesce(latest_event_at, Session.updated_at, Session.created_at)
