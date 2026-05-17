from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import Session
from app.services.session_operations import _ordered_session_query


def test_status_sort_requires_active_session_status_for_working_rank() -> None:
    """Stale live_activity cannot pull completed sessions into the working rank."""
    statement = _ordered_session_query(select(Session.id), "status", "asc")

    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "WHEN (sessions.status = %(status_1)s) THEN CASE" in sql
    assert compiled.params["status_1"] == "active"
    assert compiled.params["status_2"] == "failed"
