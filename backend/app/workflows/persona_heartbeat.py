"""Persona heartbeat — periodic system check via cron.

Cron fires every 5 minutes as a check frequency. The actual heartbeat
interval is configurable via the persona table (default: 60 minutes).
On each tick, the workflow checks if enough time has elapsed since the
last run and skips if not.
"""

from __future__ import annotations

import logging
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel

from app.hatchet_app import hatchet
from app.services.tools.direct_executor_core import KNOWN_ROOTS
from app.workflows._heartbeat_postprocess import fallback_journal, postprocess_heartbeat
from app.workflows._heartbeat_prompt import (
    build_heartbeat_prompt,
)
from app.workflows._heartbeat_redis import (
    check_redis_elapsed,
    clear_heartbeat_running,
    get_model_review_status,
    record_heartbeat,
    set_heartbeat_running,
)

logger = logging.getLogger(__name__)

HEARTBEAT_PROJECT = "summitflow"
HEARTBEAT_MEMORY_GROUP = "project:summitflow"
_DEFAULT_INTERVAL_MINUTES = 60


class HeartbeatInput(BaseModel):
    manual: bool = False


class HeartbeatResult(BaseModel):
    status: str
    turns: int = 0
    tool_calls: int = 0
    interval_minutes: int = _DEFAULT_INTERVAL_MINUTES
    error: str | None = None
    format_compliant: bool = True
    summary_stored: bool = False
    auto_journaled: bool = False


async def _resolve_persona(db: Any) -> tuple[str, str, float, str | None, str, dict[str, Any] | None]:
    """Return (model, provider, temperature, thinking_level, system_content, memory_config) for persona agent."""
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_routing_utils import inject_agent_mandates
    from app.services.agent_service import get_agent_service

    agent_service = get_agent_service()
    agent = await agent_service.get_by_slug(db, "persona")
    if not agent:
        raise RuntimeError("Persona agent not found in database")
    provider = get_provider_for_model(agent.primary_model_id)
    mandate = await inject_agent_mandates(
        agent, db, prompt_mode="full", project_id=HEARTBEAT_PROJECT, task_type="heartbeat"
    )
    return agent.primary_model_id, provider, agent.temperature, agent.thinking_level, mandate.system_content, agent.memory_config


async def get_heartbeat_interval() -> tuple[int, bool]:
    """Return (interval_minutes, onboarding_complete) from the persona table."""
    from app.db import async_session
    from app.services.persona_service import get_persona

    async with async_session() as db:
        persona = await get_persona(db)
        if persona:
            return persona.heartbeat_interval_minutes, persona.onboarding_complete
    return _DEFAULT_INTERVAL_MINUTES, False


async def _should_run() -> tuple[bool, int, bool]:
    """Return (should_run, interval_minutes, onboarding_complete) based on schedule.

    Skips if onboarding is not complete or if heartbeat is disabled.
    """
    interval_minutes, onboarding_complete = await get_heartbeat_interval()

    if not onboarding_complete:
        return False, interval_minutes, onboarding_complete
    if interval_minutes == 0:
        return False, 0, onboarding_complete

    elapsed = await check_redis_elapsed(interval_minutes)
    return elapsed, interval_minutes, onboarding_complete


def _get_skip_reason(interval_minutes: int, onboarding_complete: bool) -> str:
    """Return a human-readable reason the heartbeat was skipped."""
    if interval_minutes == 0:
        return "disabled"
    return "not onboarded" if not onboarding_complete else "interval not elapsed"


async def check_project_permission() -> bool:
    """Return False if the heartbeat project permission_tier is 'off'."""
    from app.db import async_session
    from app.services.project_permission_service import get_project_permission

    async with async_session() as perm_db:
        perm = await get_project_permission(perm_db, HEARTBEAT_PROJECT)
        return not (perm and perm.permission_tier == "off")


def _build_messages(system_content: str, prompt: str) -> list[dict[str, Any]]:
    """Assemble the messages list for complete_internal."""
    messages: list[dict[str, Any]] = []
    if system_content:
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": prompt})
    return messages


async def _execute_heartbeat(interval_minutes: int) -> HeartbeatResult:
    """Run completion and record result; returns a HeartbeatResult."""
    try:
        result = await _do_completion(interval_minutes)
    except Exception as e:
        logger.warning("Heartbeat completion failed: %s", e)
        await fallback_journal(str(e))
        return HeartbeatResult(
            status="error", error=str(e), interval_minutes=interval_minutes
        )
    return await postprocess_heartbeat(result, interval_minutes)


async def _do_completion(interval_minutes: int):
    """Run the actual completion call — separated for error handling."""
    from app.api.complete.core import complete_internal
    from app.db import async_session

    model_review_due, model_review_label = await get_model_review_status()
    heartbeat_prompt = await build_heartbeat_prompt(model_review_due, model_review_label)

    async with async_session() as db:
        model, provider, temperature, thinking_level, system_content, agent_memory_config = await _resolve_persona(db)
        result = await complete_internal(
            messages=_build_messages(system_content, heartbeat_prompt),
            model=model,
            provider=provider,
            temperature=temperature,
            project_id=HEARTBEAT_PROJECT,
            db=db,
            agent_slug="persona",
            use_memory=True,
            memory_group_id=HEARTBEAT_MEMORY_GROUP,
            memory_config=agent_memory_config,
            enable_caching=False,
            skip_cache=True,
            max_turns=25,
            execute_tools=True,
            enable_programmatic_tools=True,
            task_type="heartbeat",
            thinking_level=thinking_level,
            working_dir=KNOWN_ROOTS.get(HEARTBEAT_PROJECT),
        )

    await record_heartbeat(did_model_review=model_review_due)
    return result


@hatchet.task(
    name="persona-heartbeat",
    input_validator=HeartbeatInput,
    on_crons=["*/5 * * * *"],
    execution_timeout="1800s",
    concurrency=ConcurrencyExpression(
        expression="'persona_heartbeat'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def persona_heartbeat_task(input: HeartbeatInput, ctx: Context) -> dict[str, Any]:
    """Periodic persona check-in via complete_internal."""
    manual = input.manual

    # Manual triggers skip the interval check but still require onboarding + permissions
    if not manual:
        should_run, interval_minutes, onboarding_complete = await _should_run()
        if not should_run:
            reason = _get_skip_reason(interval_minutes, onboarding_complete)
            ctx.log(f"Heartbeat skipped ({reason}, interval={interval_minutes}m)")
            return HeartbeatResult(status="skipped", interval_minutes=interval_minutes).model_dump()
    else:
        interval_minutes, onboarding_complete = await get_heartbeat_interval()
        if not onboarding_complete:
            ctx.log("Manual heartbeat skipped (not onboarded)")
            return HeartbeatResult(status="skipped", interval_minutes=interval_minutes).model_dump()

    if not await check_project_permission():
        ctx.log("Heartbeat skipped (project_permission_off)")
        return HeartbeatResult(status="skipped", interval_minutes=interval_minutes).model_dump()

    await set_heartbeat_running()
    try:
        out = await _execute_heartbeat(interval_minutes)
        ctx.log(f"Persona heartbeat: {out.turns} turns, {out.tool_calls} tool calls")
        return out.model_dump()
    finally:
        await clear_heartbeat_running()
