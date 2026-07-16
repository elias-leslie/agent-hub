"""Consultation-related tool implementations for DirectToolExecutor.

Handles agent consultation, dispatch, steering, listing, and cancellation.
Specialist dispatch logic lives in _executor_dispatch.py.
Private helpers and observability functions live in _executor_consultation_helpers.py.
"""

from __future__ import annotations

import logging
from typing import Any

from ._executor_consultation_helpers import (
    _build_consultation_messages,
    _consultation_max_turns,
    _consultation_tools,
    cancel_consultation,
    inspect_session,
    list_consultations,
    parent_dispatch_limit_block,
    query_sessions,
)
from ._executor_dispatch import (
    _SPECIALIST_AGENT_SLUGS,
    SpecialistDispatchPlan,
    dispatch_result_text,
    parse_specialist_dispatch_request,
    prepare_specialist_dispatch,
)
from ._executor_persona_history import search_persona_history

__all__ = [
    "cancel_consultation",
    "consult_agent",
    "dispatch_agent",
    "inspect_session",
    "list_consultations",
    "query_sessions",
    "search_persona_history",
    "steer_consultation",
]

logger = logging.getLogger(__name__)


async def dispatch_agent(
    project_id: str | None,
    agent_slug: str,
    task: str,
    max_turns: int | None = None,
    parent_session_id: str | None = None,
) -> str:
    """Dispatch an agent via Hatchet wake workflow (fire-and-forget)."""
    if not project_id:
        return "Error: project_id not configured, cannot dispatch agent"
    try:
        from app.db import async_session
        from app.services.agent_routing_utils import resolve_agent
        from app.workflows.persona_wake import dispatch_wake

        async with async_session() as db:
            block_reason = await parent_dispatch_limit_block(db, parent_session_id)
            if block_reason:
                return block_reason
            resolved = await resolve_agent(agent_slug, db)
            dispatch_request = parse_specialist_dispatch_request(task)
            dispatch_plan = (
                await prepare_specialist_dispatch(
                    db=db, project_id=project_id, agent_slug=agent_slug, task=task,
                )
                if dispatch_request.mode is not None or agent_slug in _SPECIALIST_AGENT_SLUGS
                else SpecialistDispatchPlan(event_type="dispatch")
            )

        wake_kwargs: dict[str, Any] = {
            "agent_slug": agent_slug,
            "model": resolved.model,
            "provider": resolved.provider,
            "temperature": resolved.agent.temperature,
            "prompt": task,
            "project_id": project_id,
            "event_type": dispatch_plan.event_type,
            "thinking_level": resolved.agent.thinking_level,
            "max_turns": max_turns,
            "parent_session_id": parent_session_id,
            "current_branch": dispatch_plan.current_branch,
            "working_dir": dispatch_plan.working_dir,
        }
        if dispatch_plan.event_type == "dispatch_task" and dispatch_request.task_id:
            wake_kwargs["task_id"] = dispatch_request.task_id

        dispatch_wake(**wake_kwargs)
        return dispatch_result_text(agent_slug, bool(resolved.agent.is_coding_agent), task)
    except ValueError as e:
        return str(e)
    except Exception as e:
        logger.exception(f"dispatch_agent failed for '{agent_slug}'")
        return f"Error dispatching agent '{agent_slug}': {e}"


async def consult_agent(
    project_id: str | None,
    agent_slug: str,
    question: str,
    context: str = "",
    parent_session_id: str | None = None,
) -> str:
    """Consult another agent for advice with read-only research tools."""
    if not project_id:
        return "Error: project_id not configured, cannot consult agent"

    prompt = f"Context:\n{context}\n\nQuestion:\n{question}" if context else question

    try:
        from app.api.complete.core import complete_internal
        from app.db import async_session
        from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

        async with async_session() as db:
            resolved = await resolve_agent(agent_slug, db)
            mandate = await inject_agent_mandates(
                resolved.agent, db, prompt_mode="minimal", project_id=project_id,
            )
            consultation_tools = _consultation_tools(agent_slug)
            consultation_max_turns = await _consultation_max_turns(db)
            messages = _build_consultation_messages(mandate.system_content, prompt)
            result = await complete_internal(
                messages=messages, model=resolved.model, provider=resolved.provider,
                temperature=resolved.agent.temperature, project_id=project_id,
                db=db, agent_slug=agent_slug, request_source="consultation",
                use_memory=True, memory_group_id=f"project:{project_id}",
                parent_session_id=parent_session_id,
                max_turns=consultation_max_turns,
                execute_tools=bool(consultation_tools),
                tools=consultation_tools,
            )
        session_id = result.session_id if hasattr(result, "session_id") else None
        return f"[session:{session_id}] {result.content}" if session_id else result.content
    except Exception as e:
        logger.exception(f"consult_agent failed for '{agent_slug}'")
        return f"Error consulting agent '{agent_slug}': {e}"


async def steer_consultation(project_id: str | None, session_id: str, message: str) -> str:
    """Send a follow-up message to an existing consultation session."""
    if not project_id:
        return "Error: project_id not configured"
    try:
        from app.api.complete.core import complete_internal
        from app.db import async_session
        from app.models import Session as DBSession
        from app.services.agent_routing_utils import resolve_agent

        async with async_session() as db:
            session = await db.get(DBSession, session_id)
            if not session:
                return f"Error: Session '{session_id}' not found."
            if session.request_source != "consultation":
                return f"Error: Session '{session_id}' is not a consultation."
            if not session.agent_slug:
                return f"Error: Consultation session '{session_id}' has no agent slug."

            resolved = await resolve_agent(session.agent_slug, db)
            consultation_tools = _consultation_tools(session.agent_slug)
            consultation_max_turns = await _consultation_max_turns(db)
            result = await complete_internal(
                messages=[{"role": "user", "content": message}],
                model=resolved.model,
                provider=resolved.provider,
                temperature=resolved.agent.temperature,
                project_id=project_id, db=db, session_id=session_id,
                agent_slug=session.agent_slug,
                request_source="consultation",
                use_memory=True,
                memory_group_id=f"project:{project_id}",
                thinking_level=resolved.agent.thinking_level,
                max_turns=consultation_max_turns,
                execute_tools=bool(consultation_tools),
                tools=consultation_tools,
            )
            return f"[session:{session_id}] {result.content}"
    except Exception as e:
        logger.exception("steer_consultation failed")
        return f"Error steering consultation: {e}"
