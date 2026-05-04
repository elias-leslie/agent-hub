"""Work Chats persistence helpers."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActionRequest, Session, SessionBinding, SessionEventType
from app.services.event_storage import store_child_session_lifecycle_event


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
    telegram_chat_id: str | None = None,
    telegram_thread_id: str | None = None,
    telegram_message_id: str | None = None,
    source_client: str | None = None,
    work_context: dict[str, Any] | None = None,
) -> SessionBinding:
    """Create or update the durable binding for a Work Chats pane or transport."""
    stmt = select(SessionBinding).where(SessionBinding.surface == surface)
    if pane_id:
        stmt = stmt.where(SessionBinding.pane_id == pane_id)
    elif telegram_chat_id:
        stmt = stmt.where(
            SessionBinding.telegram_chat_id == telegram_chat_id,
            SessionBinding.telegram_thread_id == telegram_thread_id,
        )
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
    binding.telegram_chat_id = telegram_chat_id
    binding.telegram_thread_id = telegram_thread_id
    binding.telegram_message_id = telegram_message_id
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
        telegram_chat_id=source.get("chat_id"),
        telegram_thread_id=source.get("thread_id"),
        telegram_message_id=source.get("message_id"),
        source_client=source.get("source_client"),
        work_context=context,
    )


async def list_session_bindings(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
    pane_id: str | None = None,
) -> list[SessionBinding]:
    stmt = select(SessionBinding).order_by(SessionBinding.updated_at.desc())
    if project_id:
        stmt = stmt.where(SessionBinding.project_id == project_id)
    if task_id:
        stmt = stmt.where(SessionBinding.task_id == task_id)
    if session_id:
        stmt = stmt.where(SessionBinding.session_id == session_id)
    if pane_id:
        stmt = stmt.where(SessionBinding.pane_id == pane_id)
    return list((await db.execute(stmt.limit(200))).scalars().all())


async def create_action_request(
    db: AsyncSession,
    *,
    session_id: str,
    prompt: str | None,
    request_type: str = "blocker",
    telegram_chat_id: str | None = None,
    telegram_thread_id: str | None = None,
    telegram_message_id: str | None = None,
    source_client: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ActionRequest:
    join_code = secrets.token_urlsafe(6)
    request = ActionRequest(
        session_id=session_id,
        request_type=request_type,
        prompt=prompt,
        telegram_chat_id=telegram_chat_id,
        telegram_thread_id=telegram_thread_id,
        telegram_message_id=telegram_message_id,
        correlation_id=secrets.token_urlsafe(12),
        join_code=join_code,
        source_client=source_client,
        metadata_=metadata or {},
    )
    db.add(request)
    await db.flush()
    session = await db.get(Session, session_id)
    if session is not None:
        await store_child_session_lifecycle_event(
            db,
            session,
            SessionEventType.CHILD_SESSION_BLOCKED,
            summary=prompt or "Child session blocked on user action",
        )
    return request


async def list_action_requests(
    db: AsyncSession,
    *,
    session_id: str | None = None,
    status: str | None = None,
) -> list[ActionRequest]:
    stmt = select(ActionRequest).order_by(ActionRequest.created_at.desc())
    if session_id:
        stmt = stmt.where(ActionRequest.session_id == session_id)
    if status:
        stmt = stmt.where(ActionRequest.status == status)
    return list((await db.execute(stmt.limit(200))).scalars().all())


async def resolve_action_request(
    db: AsyncSession,
    request_id: str,
    *,
    response_content: str | None,
) -> ActionRequest:
    request = await db.get(ActionRequest, request_id)
    if request is None:
        raise ValueError(f"Action request not found: {request_id}")
    request.status = "resolved"
    request.response_content = response_content
    request.resolved_at = datetime.now(UTC)
    await db.flush()
    return request


async def resolve_join_code(db: AsyncSession, code: str) -> SessionBinding | None:
    """Resolve /join code to a binding via pending action request."""
    action_request = (
        await db.execute(
            select(ActionRequest).where(
                ActionRequest.join_code == code,
                ActionRequest.status == "pending",
            ).limit(1)
        )
    ).scalar_one_or_none()
    if action_request is None:
        return None
    binding = (
        await db.execute(
            select(SessionBinding).where(SessionBinding.session_id == action_request.session_id).limit(1)
        )
    ).scalar_one_or_none()
    if binding is not None:
        return binding
    return await upsert_session_binding(
        db,
        session_id=action_request.session_id,
        surface="telegram",
        telegram_chat_id=action_request.telegram_chat_id,
        telegram_thread_id=action_request.telegram_thread_id,
        source_client="telegram",
    )
