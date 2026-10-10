from datetime import UTC, datetime

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


def test_every_sort_ties_on_session_id() -> None:
    for sort_by in ("status", "project", "agent", "time", "last_active"):
        sql = str(_ordered_session_query(select(Session.id), sort_by, "desc").compile(dialect=postgresql.dialect()))
        assert sql.rstrip().endswith(("sessions.id DESC", "sessions.id ASC")), sort_by


def test_list_cursor_round_trips_and_rejects_other_sorts() -> None:
    import pytest

    from app.services.session_operations import (
        decode_session_list_cursor,
        encode_session_list_cursor,
    )

    moment = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    cursor = encode_session_list_cursor("status", "asc", [1, moment, moment, "abc"])
    assert "=" not in cursor and "+" not in cursor and "/" not in cursor
    assert decode_session_list_cursor(cursor, "status", "asc", 4) == [1, moment, moment, "abc"]
    with pytest.raises(ValueError, match="does not match"):
        decode_session_list_cursor(cursor, "last_active", "desc", 2)
    with pytest.raises(ValueError, match="Invalid"):
        decode_session_list_cursor("garbage!", "status", "asc", 4)


def test_last_active_keyset_uses_row_comparison() -> None:
    from app.services.session_operations import _keyset_predicate, _session_sort_keys

    moment = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    sql = str(
        _keyset_predicate(_session_sort_keys("last_active", "desc"), [moment, "abc"]).compile(
            dialect=postgresql.dialect()
        )
    )
    assert sql.startswith("(coalesce(sessions.last_activity_at, sessions.created_at), sessions.id) <")
