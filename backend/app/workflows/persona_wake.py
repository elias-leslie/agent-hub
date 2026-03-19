"""Persona wake workflow — event-driven agent invocations.

Dispatched by the /api/wake endpoint when external events (task failures,
quality gate failures, autocode completions) need the persona's attention.
Each wake gets its own ephemeral session for isolation.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from hatchet_sdk import Context
from pydantic import BaseModel
from sqlalchemy import select

from app.hatchet_app import hatchet
from app.models.session import Session
from app.workflows._session_postprocess import ensure_session_summary

logger = logging.getLogger(__name__)


class WakeInput(BaseModel):
    agent_slug: str
    model: str
    provider: str
    temperature: float = 0.7
    prompt: str
    project_id: str = "summitflow"
    event_type: str = "generic"
    thinking_level: str | None = None
    max_turns: int | None = None
    parent_session_id: str | None = None
    current_branch: str | None = None
    working_dir: str | None = None
    task_id: str | None = None


class WakeResult(BaseModel):
    status: str
    turns: int = 0
    tool_calls: int = 0
    event_type: str = "generic"
    error: str | None = None
    summary_stored: bool = False


async def _build_wake_prompt(prompt: str) -> str:
    """Prefix wake prompts with concise operational hints to reduce CLI thrash."""
    from app.services.persona_prompt_service import get_persona_wake_guidance

    prompt = prompt.strip()
    wake_guidance = await get_persona_wake_guidance()
    return f"{wake_guidance}\nTask:\n{prompt}" if prompt else wake_guidance.strip()


def _wake_external_id(ctx: Context, task_id: str | None = None) -> str | None:
    """Build external_id: prefer task_id for narration linkage, fall back to step_run_id."""
    if task_id:
        return task_id
    return f"wake-step:{ctx.step_run_id}" if getattr(ctx, "step_run_id", None) else None


async def _find_existing_wake_session(
    db: Any,
    *,
    external_id: str | None,
    project_id: str,
    agent_slug: str,
) -> Session | None:
    """Return an existing wake session for the same Hatchet step run if present."""
    if not external_id:
        return None
    result = await db.execute(
        select(Session)
        .where(
            Session.external_id == external_id,
            Session.project_id == project_id,
            Session.agent_slug == agent_slug,
        )
        .order_by(Session.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@hatchet.task(
    name="agent-wake",
    execution_timeout="7200s",
    retries=0,
    input_validator=WakeInput,
)
async def agent_wake_task(input: WakeInput, ctx: Context) -> dict[str, Any]:
    """Run an agent completion in response to an external event."""
    from app.api.complete.core import complete_internal
    from app.db import async_session
    from app.services.project_permission_service import get_project_permission

    # Check project permission — skip if tier is "off"
    async with async_session() as perm_db:
        perm = await get_project_permission(perm_db, input.project_id)
        if perm and perm.permission_tier == "off":
            ctx.log(f"Wake skipped for {input.project_id} (permission_tier=off)")
            return WakeResult(
                status="skipped",
                event_type=input.event_type,
                error="project_permission_off",
            ).model_dump()

    memory_group = f"{input.project_id}:wake:{input.event_type}"
    external_id = _wake_external_id(ctx, task_id=input.task_id)

    # Hatchet step-run dedup ID (only used for replay detection, not as external_id)
    step_dedup_id = f"wake-step:{ctx.step_run_id}" if getattr(ctx, "step_run_id", None) else None

    # Resolve max_turns: explicit > persona limit > 200 fallback
    from app.services._persona_crud import get_persona_limit
    from app.services.persona_service import get_persona

    async with async_session() as db:
        existing = await _find_existing_wake_session(
            db,
            external_id=step_dedup_id,
            project_id=input.project_id,
            agent_slug=input.agent_slug,
        )
        if existing is not None:
            ctx.log(
                "Wake replay detected; reusing prior session "
                f"{existing.id} for step_run_id={ctx.step_run_id}"
            )
            return WakeResult(
                status="skipped",
                event_type=input.event_type,
                error=f"duplicate_step_run:{existing.id}",
                summary_stored=bool(existing.summary_oneliner or existing.summary_generated_at),
            ).model_dump()

        if input.max_turns:
            max_turns = input.max_turns
        else:
            persona = await get_persona(db)
            max_turns = get_persona_limit(persona, "max_turns") or 200

        try:
            result = await complete_internal(
                messages=[{"role": "user", "content": await _build_wake_prompt(input.prompt)}],
                model=input.model,
                provider=input.provider,
                temperature=input.temperature,
                project_id=input.project_id,
                db=db,
                external_id=external_id,
                request_source=f"persona_wake:{input.event_type}",
                agent_slug=input.agent_slug,
                use_memory=True,
                memory_group_id=memory_group,
                enable_caching=False,
                skip_cache=True,
                max_turns=max_turns,
                execute_tools=True,
                enable_programmatic_tools=True,
                defer_tool_loading=True,
                task_type="wake",
                phase=input.event_type,
                thinking_level=input.thinking_level,
                parent_session_id=input.parent_session_id,
                current_branch=input.current_branch,
                working_dir=input.working_dir,
            )
        except asyncio.CancelledError:
            with suppress(Exception):
                await db.rollback()
            with suppress(Exception):
                await db.close()
            raise

    summary_stored = await ensure_session_summary(
        result.session_id,
        result.content or "",
        agent_id=input.agent_slug,
    )

    out = WakeResult(
        status=result.status or "success",
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        event_type=input.event_type,
        error=result.error,
        summary_stored=summary_stored,
    )
    ctx.log(
        f"Agent wake ({input.agent_slug}/{input.event_type}): "
        f"{out.turns} turns, {out.tool_calls} tool calls, summary_stored={summary_stored}"
    )
    return out.model_dump()


def dispatch_wake(
    agent_slug: str,
    model: str,
    provider: str,
    temperature: float,
    prompt: str,
    project_id: str,
    event_type: str,
    thinking_level: str | None = None,
    max_turns: int | None = None,
    parent_session_id: str | None = None,
    current_branch: str | None = None,
    working_dir: str | None = None,
    task_id: str | None = None,
) -> None:
    """Dispatch a wake workflow via Hatchet (fire-and-forget)."""
    wake_input = WakeInput(
        agent_slug=agent_slug,
        model=model,
        provider=provider,
        temperature=temperature,
        prompt=prompt,
        project_id=project_id,
        event_type=event_type,
        thinking_level=thinking_level,
        max_turns=max_turns,
        parent_session_id=parent_session_id,
        current_branch=current_branch,
        working_dir=working_dir,
        task_id=task_id,
    )
    agent_wake_task.run_no_wait(wake_input)
    logger.info("Dispatched wake workflow for %s/%s", agent_slug, event_type)
