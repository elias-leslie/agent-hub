"""Memory scope normalization helpers.

Normalizes legacy scope encodings to canonical form:
- scope='project', scope_id='<project-id>'
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_revisions import RevisionRepository

SCOPE_NORMALIZATION_ACTOR = "system:scope-normalization"


def _normalized_scope(memory: Memory) -> tuple[dict[str, str | None], list[str]]:
    """The canonical scope fields for one row and which legacy rules applied, in order."""
    scope, scope_id, group_id = memory.scope, memory.scope_id or None, memory.group_id or None
    rules: list[str] = []
    if scope.startswith("project:"):
        target = scope.split(":")[1]
        scope, scope_id, group_id = "project", scope_id or target, group_id or f"project-{target}"
        rules.append("legacy_prefixed_scope")
    if scope == "global" and (group_id or "").startswith("project-"):
        scope, scope_id = "project", scope_id or (group_id or "")[8:]
        rules.append("global_scope_project_group")
    if scope == "project" and not scope_id and (group_id or "").startswith("project-"):
        scope_id = (group_id or "")[8:]
        rules.append("project_scope_missing_scope_id")
    return {"scope": scope, "scope_id": scope_id, "group_id": group_id}, rules


async def normalize_legacy_scope_rows() -> dict[str, int]:
    """Normalize legacy memory scope rows, each with a revision, and return per-rule row counts."""
    counts = {"legacy_prefixed_scope": 0, "global_scope_project_group": 0, "project_scope_missing_scope_id": 0}
    candidates = select(Memory).where(or_(
        Memory.scope.like("project:%"),
        and_(Memory.scope == "global", Memory.group_id.like("project-%")),
        and_(Memory.scope == "project", or_(Memory.scope_id.is_(None), Memory.scope_id == ""),
             Memory.group_id.like("project-%")),
    )).with_for_update()
    async with async_session() as session:
        revisions = RevisionRepository()
        for memory in (await session.execute(candidates)).scalars().all():
            fields, rules = _normalized_scope(memory)
            if not rules:
                continue
            for rule in rules:
                counts[rule] += 1
            for key, value in fields.items():
                setattr(memory, key, value)
            memory.version = int(memory.version or 1) + 1
            memory.updated_at = datetime.now(UTC)
            await session.flush()
            await revisions.record_revision(
                session, memory, action="scope_normalize", changed_by=SCOPE_NORMALIZATION_ACTOR,
                change_reason="Legacy scope encoding normalized: " + ", ".join(rules),
            )
        await session.commit()
    return counts


def normalize_scope_identity(scope: str, scope_id: str | None) -> tuple[str, str | None]:
    """Read legacy project/agent prefixes without broadening an unknown scope."""
    kind, separator, target = scope.partition(":")
    if separator and kind in {"project", "agent"}:
        return kind, scope_id or target or None
    return scope, scope_id
