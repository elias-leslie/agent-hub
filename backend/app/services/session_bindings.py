"""Session binding persistence for request-level work context and source metadata.

`/api/complete` callers (for example design-tools `st.design.asset.critique`) send
`work_context`/`source_metadata`; these helpers merge them onto the session row and
upsert the durable `session_bindings` row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, SessionBinding


def _dump(value: Any | None) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    return dict(value) if isinstance(value, dict) else {}


def apply_work_chat_metadata(
    session: Session,
    *,
    work_context: Any | None = None,
    source_metadata: Any | None = None,
) -> None:
    """Merge Work Chats request metadata onto a session row."""
    context = _dump(work_context)
    source = _dump(source_metadata)
    if not context and not source:
        return
    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    if context:
        metadata["work_context"] = context
    if source:
        metadata["source_metadata"] = source
        for key in ("source_client", "transport", "surface", "pane_id"):
            if source.get(key):
                metadata[key] = source[key]
    session.provider_metadata = metadata


async def upsert_session_binding(
    db: AsyncSession,
    *,
    session_id: str,
    surface: str = "work_chats",
    pane_id: str | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
    feedback_id: str | None = None,
    design_id: str | None = None,
    source_client: str | None = None,
    work_context: dict[str, Any] | None = None,
) -> SessionBinding:
    """Create or update the durable binding for a Work Chats pane or request surface."""
    stmt = select(SessionBinding).where(SessionBinding.surface == surface)
    if pane_id:
        stmt = stmt.where(SessionBinding.pane_id == pane_id)
    else:
        stmt = stmt.where(
            SessionBinding.session_id == session_id,
            SessionBinding.project_id == project_id,
            SessionBinding.task_id == task_id,
            SessionBinding.feedback_id == feedback_id,
            SessionBinding.design_id == design_id,
        )
    binding = (await db.execute(stmt.limit(1))).scalar_one_or_none()
    if binding is None:
        binding = SessionBinding(surface=surface, pane_id=pane_id, session_id=session_id)
        db.add(binding)
    binding.session_id = session_id
    binding.project_id = project_id
    binding.task_id = task_id
    binding.feedback_id = feedback_id
    binding.design_id = design_id
    binding.source_client = source_client
    binding.work_context = work_context or {}
    binding.updated_at = datetime.now(UTC)
    await db.flush()
    return binding


async def bind_request_context(
    db: AsyncSession,
    *,
    session: Session,
    work_context: Any | None,
    source_metadata: Any | None,
) -> None:
    """Persist request-level Work Chats binding when pane/source metadata is present."""
    context = _dump(work_context)
    source = _dump(source_metadata)
    apply_work_chat_metadata(session, work_context=context, source_metadata=source)
    pane_id = source.get("pane_id") or context.get("pane_id")
    if not (pane_id or context or source):
        return
    await upsert_session_binding(
        db,
        session_id=session.id,
        surface=str(source.get("surface") or context.get("surface") or "work_chats"),
        pane_id=str(pane_id) if pane_id else None,
        project_id=context.get("project_id") or session.project_id,
        task_id=context.get("task_id") or session.external_id,
        feedback_id=context.get("feedback_id"),
        design_id=context.get("design_id"),
        source_client=source.get("source_client"),
        work_context=context,
    )
