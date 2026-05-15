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
from app.workflows._session_postprocess import (
    ensure_session_summary,
    inline_summary_contract_issues,
    progress_tag_contract_issues,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

TASK_NAME = "agent-wake"
DEFAULT_PROJECT_ID = "summitflow"
DEFAULT_EVENT_TYPE = "generic"
PERMISSION_TIER_OFF = "off"
TASK_TYPE_WAKE = "wake"
LOGGED_BY_SYSTEM = "system"
FEEDBACK_TYPE_FRICTION = "friction"
OUTCOME_PARTIAL = "partial"
TAG_OBSERVATION_PREFIX = "Wake tagging contract gap: "
REQUEST_SOURCE_PREFIX = "persona_wake:"


async def log_agent_performance(*args: Any, **kwargs: Any) -> str:
    """Lazily import performance logging so tests can patch the wake seam."""
    from app.services.tools._executor_performance import (
        log_agent_performance as _log_agent_performance,
    )

    return await _log_agent_performance(*args, **kwargs)


class WakeInput(BaseModel):
    agent_slug: str
    model: str
    provider: str
    temperature: float = 0.7
    prompt: str
    project_id: str = DEFAULT_PROJECT_ID
    event_type: str = DEFAULT_EVENT_TYPE
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
    event_type: str = DEFAULT_EVENT_TYPE
    error: str | None = None
    summary_stored: bool = False


def _build_wake_tag_observation(
    *,
    content: str | None,
    task_id: str | None,
) -> dict[str, str] | None:
    """Return a wake-session observability note when required tags are missing."""
    notes = [
        *inline_summary_contract_issues(content),
        *progress_tag_contract_issues(content, require_progress=bool(task_id)),
    ]
    if not notes:
        return None
    return {
        "feedback_type": FEEDBACK_TYPE_FRICTION,
        "outcome": OUTCOME_PARTIAL,
        "content": TAG_OBSERVATION_PREFIX + "; ".join(notes),
    }


async def _log_wake_tag_observation(
    *,
    input: WakeInput,
    result: Any,
) -> None:
    observation = _build_wake_tag_observation(
        content=result.content or "",
        task_id=input.task_id,
    )
    if observation is None:
        return
    try:
        await log_agent_performance(
            agent_slug=input.agent_slug,
            model_id=getattr(result, "model_used", None) or getattr(result, "model", None) or input.model,
            feedback_type=observation["feedback_type"],
            content=observation["content"],
            outcome=observation["outcome"],
            task_type=TASK_TYPE_WAKE,
            project_id=input.project_id,
            session_id=result.session_id,
            input_tokens=getattr(result, "input_tokens", None),
            output_tokens=getattr(result, "output_tokens", None),
            tool_calls_count=result.tool_calls_count,
            turns=result.turns,
            logged_by=LOGGED_BY_SYSTEM,
        )
    except Exception:
        logger.debug("Failed to log wake tagging observation", exc_info=True)


async def _build_wake_prompt(prompt: str) -> str:
    """Prefix wake prompts with concise operational hints to reduce CLI thrash."""
    from app.services.persona_prompt_service import get_persona_wake_guidance

    prompt = prompt.strip()
    wake_guidance = await get_persona_wake_guidance()
    return f"{wake_guidance}\nTask:\n{prompt}" if prompt else wake_guidance.strip()


def _resolve_wake_working_dir(project_id: str, working_dir: str | None) -> str | None:
    """Prefer explicit working_dir, else fall back to the project's canonical root."""
    if working_dir:
        return working_dir

    from app.core.project_roots import resolve_project_root

    root = resolve_project_root(project_id)
    return str(root) if root else None


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


async def _resolve_max_turns(db: Any, input: WakeInput) -> int | None:
    """Return only an explicit caller-directed turn cap."""
    del db
    return input.max_turns


async def _check_permission_tier(project_id: str) -> bool:
    """Return True if the project is allowed to run wake workflows."""
    from app.db import async_session
    from app.services.project_permission_service import get_project_permission

    async with async_session() as perm_db:
        perm = await get_project_permission(perm_db, project_id)
        return not (perm and perm.permission_tier == PERMISSION_TIER_OFF)


async def _run_complete_guarded(
    db: Any,
    input: WakeInput,
    external_id: str | None,
    max_turns: int | None,
) -> Any:
    """Run complete_internal and handle CancelledError cleanup."""
    try:
        return await _run_complete_internal(db, input, external_id, max_turns)
    except asyncio.CancelledError:
        with suppress(Exception):
            await db.rollback()
        with suppress(Exception):
            await db.close()
        raise


async def _run_complete_internal(db: Any, input: WakeInput, external_id: str | None, max_turns: int | None) -> Any:
    """Invoke complete_internal with wake-specific parameters."""
    from app.api.complete.core import complete_internal

    return await complete_internal(
        messages=[{"role": "user", "content": await _build_wake_prompt(input.prompt)}],
        model=input.model,
        provider=input.provider,
        temperature=input.temperature,
        project_id=input.project_id,
        db=db,
        external_id=external_id,
        request_source=f"{REQUEST_SOURCE_PREFIX}{input.event_type}",
        agent_slug=input.agent_slug,
        use_memory=True,
        memory_group_id=f"{input.project_id}:{TASK_TYPE_WAKE}:{input.event_type}",
        enable_caching=False,
        skip_cache=True,
        max_turns=max_turns,
        execute_tools=True,
        enable_programmatic_tools=True,
        defer_tool_loading=True,
        task_type=TASK_TYPE_WAKE,
        phase=input.event_type,
        thinking_level=input.thinking_level,
        parent_session_id=input.parent_session_id,
        current_branch=input.current_branch,
        working_dir=_resolve_wake_working_dir(input.project_id, input.working_dir),
    )


@hatchet.task(
    name=TASK_NAME,
    retries=0,
    input_validator=WakeInput,
)
async def agent_wake_task(input: WakeInput, ctx: Context) -> dict[str, Any]:
    """Run an agent completion in response to an external event."""
    from app.db import async_session

    if not await _check_permission_tier(input.project_id):
        ctx.log(f"Wake skipped for {input.project_id} (permission_tier=off)")
        return WakeResult(status="skipped", event_type=input.event_type, error="project_permission_off").model_dump()

    external_id = _wake_external_id(ctx, task_id=input.task_id)
    step_dedup_id = f"wake-step:{ctx.step_run_id}" if getattr(ctx, "step_run_id", None) else None

    async with async_session() as db:
        existing = await _find_existing_wake_session(
            db, external_id=step_dedup_id, project_id=input.project_id, agent_slug=input.agent_slug,
        )
        if existing is not None:
            ctx.log(f"Wake replay detected; reusing prior session {existing.id} for step_run_id={ctx.step_run_id}")
            return WakeResult(
                status="skipped",
                event_type=input.event_type,
                error=f"duplicate_step_run:{existing.id}",
                summary_stored=bool(existing.summary_oneliner or existing.summary_generated_at),
            ).model_dump()
        max_turns = await _resolve_max_turns(db, input)
        result = await _run_complete_guarded(db, input, external_id, max_turns)

    summary_stored = await ensure_session_summary(result.session_id, result.content or "", agent_id=input.agent_slug)
    await _log_wake_tag_observation(input=input, result=result)
    out = WakeResult(
        status=result.status or "success",
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        event_type=input.event_type,
        error=result.error,
        summary_stored=summary_stored,
    )
    ctx.log(f"Agent wake ({input.agent_slug}/{input.event_type}): {out.turns} turns, {out.tool_calls} tool calls, summary_stored={summary_stored}")
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
