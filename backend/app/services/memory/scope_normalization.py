"""Memory scope normalization helpers.

Normalizes legacy scope encodings to canonical form:
- scope='project', scope_id='<project-id>'
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.db import async_session


def _result_rowcount(result: Any) -> int:
    """Return integer rowcount from SQLAlchemy result objects."""
    return int(getattr(result, "rowcount", 0) or 0)


async def normalize_legacy_scope_rows() -> dict[str, int]:
    """Normalize legacy memory scope rows and return updated row counts."""
    async with async_session() as session:
        legacy_prefixed = await session.execute(text("""
            UPDATE memories
            SET
                scope = 'project',
                scope_id = COALESCE(NULLIF(scope_id, ''), split_part(scope, ':', 2)),
                group_id = COALESCE(NULLIF(group_id, ''), 'project-' || split_part(scope, ':', 2)),
                updated_at = now()
            WHERE scope LIKE 'project:%'
        """))

        global_with_project_group = await session.execute(text("""
            UPDATE memories
            SET
                scope = 'project',
                scope_id = COALESCE(NULLIF(scope_id, ''), substr(group_id, 9)),
                updated_at = now()
            WHERE scope = 'global'
              AND group_id LIKE 'project-%'
        """))

        project_missing_scope_id = await session.execute(text("""
            UPDATE memories
            SET
                scope_id = substr(group_id, 9),
                updated_at = now()
            WHERE scope = 'project'
              AND (scope_id IS NULL OR scope_id = '')
              AND group_id LIKE 'project-%'
        """))

        await session.commit()

    return {
        "legacy_prefixed_scope": _result_rowcount(legacy_prefixed),
        "global_scope_project_group": _result_rowcount(global_with_project_group),
        "project_scope_missing_scope_id": _result_rowcount(project_missing_scope_id),
    }
