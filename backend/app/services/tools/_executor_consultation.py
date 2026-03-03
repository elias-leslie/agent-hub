"""Consultation-related tool implementations for DirectToolExecutor.

Handles agent consultation, dispatch, steering, listing, and cancellation.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def dispatch_agent(
    project_id: str | None,
    agent_slug: str,
    task: str,
    max_turns: int = 25,
) -> str:
    """Dispatch an agent with full tool access to perform a task.

    Unlike consult_agent (text-only advice), dispatch_agent runs the target
    agent with execute_tools=True so it can use bash, read_file, write_file,
    agent-browser, etc. Returns the agent's final response text.
    """
    if not project_id:
        return "Error: project_id not configured, cannot dispatch agent"

    try:
        from app.api.complete.core import complete_internal
        from app.db import async_session
        from app.services._persona_crud import get_persona_limit
        from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent
        from app.services.persona_service import get_persona

        # Cap max_turns and get dispatch timeout from persona limits
        async with async_session() as db:
            persona = await get_persona(db)
            turn_cap = int(get_persona_limit(persona, "max_job_turns"))
            max_turns = min(max(1, max_turns), turn_cap)
            dispatch_timeout = float(get_persona_limit(persona, "dispatch_timeout_seconds"))

            resolved = await resolve_agent(agent_slug, db)

            mandate = await inject_agent_mandates(
                resolved.agent, db, prompt_mode="minimal",
                project_id=project_id,
            )
            messages: list[dict[str, str]] = []
            if mandate.system_content:
                messages.append({"role": "system", "content": mandate.system_content})
            messages.append({"role": "user", "content": task})

            result = await complete_internal(
                messages=messages,
                model=resolved.model,
                provider=resolved.provider,
                temperature=resolved.agent.temperature,
                project_id=project_id,
                db=db,
                agent_slug=agent_slug,
                request_source="dispatch",
                use_memory=True,
                memory_group_id=f"project-{project_id}",
                max_turns=max_turns,
                execute_tools=True,
                timeout_seconds=dispatch_timeout,
            )
            session_id = result.session_id if hasattr(result, "session_id") else None
            content = result.content
            if session_id:
                return f"[session:{session_id}] {content}"
            return content
    except Exception as e:
        logger.exception(f"dispatch_agent failed for '{agent_slug}'")
        return f"Error dispatching agent '{agent_slug}': {e}"


async def consult_agent(
    project_id: str | None,
    agent_slug: str,
    question: str,
    context: str = "",
) -> str:
    """Consult another agent for advice without executing tools."""
    if not project_id:
        return "Error: project_id not configured, cannot consult agent"

    prompt = question
    if context:
        prompt = f"Context:\n{context}\n\nQuestion:\n{question}"

    try:
        from app.api.complete.core import complete_internal
        from app.db import async_session
        from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

        async with async_session() as db:
            resolved = await resolve_agent(agent_slug, db)

            mandate = await inject_agent_mandates(
                resolved.agent, db, prompt_mode="minimal",
                project_id=project_id,
            )
            messages: list[dict[str, str]] = []
            if mandate.system_content:
                messages.append({"role": "system", "content": mandate.system_content})
            messages.append({"role": "user", "content": prompt})

            result = await complete_internal(
                messages=messages,
                model=resolved.model,
                provider=resolved.provider,
                temperature=resolved.agent.temperature,
                project_id=project_id,
                db=db,
                agent_slug=agent_slug,
                request_source="consultation",
                use_memory=True,
                memory_group_id=f"project-{project_id}",
                max_turns=1,
                execute_tools=False,
            )
            session_id = result.session_id if hasattr(result, "session_id") else None
            content = result.content
            if session_id:
                return f"[session:{session_id}] {content}"
            return content
    except Exception as e:
        logger.exception(f"consult_agent failed for '{agent_slug}'")
        return f"Error consulting agent '{agent_slug}': {e}"


async def steer_consultation(
    project_id: str | None,
    session_id: str,
    message: str,
) -> str:
    """Send a follow-up message to an existing consultation session."""
    if not project_id:
        return "Error: project_id not configured"

    try:
        import redis.asyncio as redis

        from app.api.complete.core import complete_internal
        from app.config import settings
        from app.db import async_session
        from app.services.persona_service import get_persona, get_persona_limit

        redis_client = redis.from_url(
            settings.agent_hub_redis_url, encoding="utf-8", decode_responses=True,
        )
        try:
            counter_key = f"consultation:steers:{session_id}"
            count = await redis_client.incr(counter_key)
            if count == 1:
                await redis_client.expire(counter_key, 3600)

            async with async_session() as db:
                persona = await get_persona(db)
            max_steers = get_persona_limit(persona, "max_steers_per_consultation")
            if count > max_steers:
                return (
                    f"Error: Rate limit reached ({max_steers} steers per consultation session). "
                    "Start a new consultation with consult_agent."
                )
        finally:
            await redis_client.close()

        async with async_session() as db:
            result = await complete_internal(
                messages=[{"role": "user", "content": message}],
                model="claude-haiku-4-5",
                provider="claude",
                temperature=0.3,
                project_id=project_id,
                db=db,
                session_id=session_id,
                request_source="consultation",
                max_turns=1,
                execute_tools=False,
            )
            return f"[session:{session_id}] {result.content}"
    except Exception as e:
        logger.exception("steer_consultation failed")
        return f"Error steering consultation: {e}"


async def list_consultations(
    hours_back: int = 24,
    agent_slug: str | None = None,
) -> str:
    """List recent consultation sessions."""
    try:
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import select

        from app.db import async_session
        from app.models import Session as DBSession

        cutoff = datetime.now(UTC) - timedelta(hours=hours_back)

        async with async_session() as db:
            query = (
                select(DBSession)
                .where(
                    DBSession.request_source == "consultation",
                    DBSession.created_at >= cutoff,
                )
                .order_by(DBSession.created_at.desc())
                .limit(50)
            )
            if agent_slug:
                query = query.where(DBSession.agent_slug == agent_slug)

            result = await db.execute(query)
            sessions = result.scalars().all()

        if not sessions:
            return f"(No consultations in the last {hours_back} hours)"

        lines = []
        for s in sessions:
            created = s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "?"
            lines.append(
                f"- {s.agent_slug or '?'} | session={s.id} | "
                f"status={s.status} | created={created}"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.exception("list_consultations failed")
        return f"Error listing consultations: {e}"


async def cancel_consultation(session_id: str) -> str:
    """Close a running consultation session."""
    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models import Session as DBSession

        async with async_session() as db:
            result = await db.execute(
                select(DBSession).where(DBSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if not session:
                return f"Error: Session '{session_id}' not found."

            if session.request_source != "consultation":
                return f"Error: Session '{session_id}' is not a consultation."

            session.status = "completed"
            await db.commit()
            return f"Consultation session {session_id} closed."
    except Exception as e:
        logger.exception("cancel_consultation failed")
        return f"Error cancelling consultation: {e}"
