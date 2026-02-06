import logging
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select

from app.db import _get_session_factory
from app.models import MemoryInjectionMetric, Session

logger = logging.getLogger(__name__)


class SessionMemoryInfo(BaseModel):
    session_id: str
    agent_slug: str | None
    project_id: str | None
    started_at: str
    ended_at: str | None
    episodes_loaded: int
    episodes_cited: int
    citation_rate: float
    source: str | None


class SessionMemoryList(BaseModel):
    sessions: list[SessionMemoryInfo]
    total: int


async def get_sessions_with_memory(
    limit: int = 50,
    offset: int = 0,
) -> SessionMemoryList:
    session_factory = _get_session_factory()

    try:
        async with session_factory() as db:
            count_query = (
                select(func.count(Session.id))
                .select_from(Session)
                .join(
                    MemoryInjectionMetric,
                    MemoryInjectionMetric.session_id == Session.id,
                    isouter=True,
                )
                .where(
                    (MemoryInjectionMetric.id.isnot(None))
                    | (Session.session_type.in_(["completion", "chat", "agent"]))
                )
            )
            total_result = await db.execute(count_query)
            total = total_result.scalar() or 0

            query = (
                select(
                    Session.id,
                    Session.agent_slug,
                    Session.project_id,
                    Session.created_at,
                    Session.updated_at,
                    Session.status,
                    Session.request_source,
                    Session.session_type,
                    func.coalesce(func.count(MemoryInjectionMetric.id), 0).label("injection_count"),
                    func.coalesce(
                        func.sum(
                            func.coalesce(
                                func.jsonb_array_length(
                                    func.cast(
                                        MemoryInjectionMetric.memories_loaded,
                                        _get_jsonb_type(),
                                    )
                                ),
                                0,
                            )
                        ),
                        0,
                    ).label("total_loaded"),
                    func.coalesce(
                        func.sum(
                            func.coalesce(
                                func.jsonb_array_length(
                                    func.cast(
                                        MemoryInjectionMetric.memories_cited,
                                        _get_jsonb_type(),
                                    )
                                ),
                                0,
                            )
                        ),
                        0,
                    ).label("total_cited"),
                )
                .select_from(Session)
                .join(
                    MemoryInjectionMetric,
                    MemoryInjectionMetric.session_id == Session.id,
                    isouter=True,
                )
                .group_by(Session.id)
                .having(
                    (func.count(MemoryInjectionMetric.id) > 0)
                    | (Session.session_type.in_(["completion", "chat", "agent"]))
                )
                .order_by(Session.created_at.desc())
                .offset(offset)
                .limit(limit)
            )

            result = await db.execute(query)
            rows = result.all()

            sessions = []
            for row in rows:
                loaded = int(row.total_loaded or 0)
                cited = int(row.total_cited or 0)
                citation_rate = cited / loaded if loaded > 0 else 0.0

                ended_at = None
                if row.status in ("completed", "failed"):
                    ended_at = row.updated_at.isoformat() if row.updated_at else None

                source = row.request_source or row.session_type

                sessions.append(
                    SessionMemoryInfo(
                        session_id=row.id,
                        agent_slug=row.agent_slug,
                        project_id=row.project_id,
                        started_at=row.created_at.isoformat(),
                        ended_at=ended_at,
                        episodes_loaded=loaded,
                        episodes_cited=cited,
                        citation_rate=round(citation_rate, 3),
                        source=source,
                    )
                )

            return SessionMemoryList(sessions=sessions, total=total)

    except Exception as e:
        logger.error("Failed to get sessions with memory: %s", e)
        return SessionMemoryList(sessions=[], total=0)


def _get_jsonb_type() -> Any:
    from sqlalchemy.dialects.postgresql import JSONB

    return JSONB
