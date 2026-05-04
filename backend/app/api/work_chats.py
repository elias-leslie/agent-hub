"""Work Chats API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ActionRequest, SessionBinding
from app.services.event_storage import store_message_event
from app.services.work_chats import (
    create_action_request,
    list_action_requests,
    list_session_bindings,
    resolve_action_request,
    resolve_join_code,
    upsert_session_binding,
)

router = APIRouter(prefix="/work-chats", tags=["work-chats"])


class SessionBindingRequest(BaseModel):
    session_id: str
    surface: str = "work_chats"
    pane_id: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    feedback_id: str | None = None
    design_id: str | None = None
    telegram_chat_id: str | None = None
    telegram_thread_id: str | None = None
    telegram_message_id: str | None = None
    source_client: str | None = None
    work_context: dict[str, Any] = Field(default_factory=dict)


class SessionBindingResponse(SessionBindingRequest):
    id: str
    created_at: datetime
    updated_at: datetime


class SessionBindingsResponse(BaseModel):
    bindings: list[SessionBindingResponse]


class ActionRequestCreate(BaseModel):
    session_id: str
    prompt: str | None = None
    request_type: str = "blocker"
    telegram_chat_id: str | None = None
    telegram_thread_id: str | None = None
    telegram_message_id: str | None = None
    source_client: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionRequestResolve(BaseModel):
    response_content: str | None = None


class ActionRequestResponse(BaseModel):
    id: str
    session_id: str
    status: str
    request_type: str
    prompt: str | None
    response_content: str | None
    telegram_chat_id: str | None
    telegram_thread_id: str | None
    telegram_message_id: str | None
    correlation_id: str | None
    join_code: str | None
    source_client: str | None
    metadata: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None
    expires_at: datetime | None


class ActionRequestsResponse(BaseModel):
    action_requests: list[ActionRequestResponse]


class JoinResponse(BaseModel):
    binding: SessionBindingResponse | None


def _binding_response(binding: SessionBinding) -> SessionBindingResponse:
    return SessionBindingResponse(
        id=str(binding.id),
        session_id=binding.session_id,
        surface=binding.surface,
        pane_id=binding.pane_id,
        project_id=binding.project_id,
        task_id=binding.task_id,
        feedback_id=binding.feedback_id,
        design_id=binding.design_id,
        telegram_chat_id=binding.telegram_chat_id,
        telegram_thread_id=binding.telegram_thread_id,
        telegram_message_id=binding.telegram_message_id,
        source_client=binding.source_client,
        work_context=binding.work_context or {},
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


def _action_response(request: ActionRequest) -> ActionRequestResponse:
    return ActionRequestResponse(
        id=str(request.id),
        session_id=request.session_id,
        status=request.status,
        request_type=request.request_type,
        prompt=request.prompt,
        response_content=request.response_content,
        telegram_chat_id=request.telegram_chat_id,
        telegram_thread_id=request.telegram_thread_id,
        telegram_message_id=request.telegram_message_id,
        correlation_id=request.correlation_id,
        join_code=request.join_code,
        source_client=request.source_client,
        metadata=request.metadata_ or {},
        created_at=request.created_at,
        resolved_at=request.resolved_at,
        expires_at=request.expires_at,
    )


@router.get("/bindings", response_model=SessionBindingsResponse)
async def get_bindings(
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: Annotated[str | None, Query()] = None,
    task_id: Annotated[str | None, Query()] = None,
    session_id: Annotated[str | None, Query()] = None,
    pane_id: Annotated[str | None, Query()] = None,
) -> SessionBindingsResponse:
    bindings = await list_session_bindings(
        db,
        project_id=project_id,
        task_id=task_id,
        session_id=session_id,
        pane_id=pane_id,
    )
    return SessionBindingsResponse(bindings=[_binding_response(binding) for binding in bindings])


@router.post("/bindings", response_model=SessionBindingResponse, status_code=201)
async def create_or_update_binding(
    request: SessionBindingRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionBindingResponse:
    binding = await upsert_session_binding(db, **request.model_dump())
    await db.commit()
    return _binding_response(binding)


@router.get("/action-requests", response_model=ActionRequestsResponse)
async def get_action_requests(
    db: Annotated[AsyncSession, Depends(get_db)],
    session_id: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
) -> ActionRequestsResponse:
    requests = await list_action_requests(db, session_id=session_id, status=status)
    return ActionRequestsResponse(action_requests=[_action_response(request) for request in requests])


@router.post("/action-requests", response_model=ActionRequestResponse, status_code=201)
async def create_action_request_endpoint(
    request: ActionRequestCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ActionRequestResponse:
    action_request = await create_action_request(db, **request.model_dump())
    await db.commit()
    return _action_response(action_request)


@router.post("/action-requests/{request_id}/resolve", response_model=ActionRequestResponse)
async def resolve_action_request_endpoint(
    request_id: str,
    request: ActionRequestResolve,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ActionRequestResponse:
    try:
        action_request = await resolve_action_request(
            db,
            request_id,
            response_content=request.response_content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if request.response_content:
        await store_message_event(
            db,
            action_request.session_id,
            "user",
            request.response_content,
            transport="telegram" if action_request.telegram_chat_id else None,
            surface="work_chats",
            chat_id=action_request.telegram_chat_id,
            message_id=action_request.telegram_message_id,
            source_client=action_request.source_client,
        )
    await db.commit()
    return _action_response(action_request)


@router.get("/telegram/join/{code}", response_model=JoinResponse)
async def join_work_chat(code: str, db: Annotated[AsyncSession, Depends(get_db)]) -> JoinResponse:
    binding = await resolve_join_code(db, code)
    await db.commit()
    return JoinResponse(binding=_binding_response(binding) if binding else None)
