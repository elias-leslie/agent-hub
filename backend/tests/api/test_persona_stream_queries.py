from __future__ import annotations

from app.api.persona.stream_queries import _persona_session_query
from app.api.persona.stream_search import _parse_search


def test_persona_session_query_casts_status_enum_for_ilike() -> None:
    query = _persona_session_query(hours=24, parsed_search=_parse_search("status:completed"))
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))

    assert "lower(CAST(sessions.status AS VARCHAR)) LIKE lower('%completed%')" in compiled
