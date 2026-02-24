"""Persona heartbeat — periodic system check via cron.

Cron fires every 5 minutes as a check frequency. The actual heartbeat
interval is configurable via the persona table (default: 60 minutes).
On each tick, the workflow checks if enough time has elapsed since the
last run and skips if not.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel

from app.hatchet_app import hatchet

logger = logging.getLogger(__name__)

HEARTBEAT_PROMPT = (
    "Run your regular heartbeat check. Specifically:\n"
    "1. Call `manage_tasks` to review pending/blocked tasks and check progress.\n"
    "2. Call `list_consultations` to see if any consultations need attention.\n"
    "3. Call `list_scheduled_jobs` to verify scheduled work is running on time.\n"
    "4. Call `read_journal` to review your recent observations and decisions.\n"
    "5. After your review, call `write_journal` with an observation entry summarizing "
    "what you found and any actions taken.\n\n"
    "Only `send_push` if something genuinely needs human attention — don't push for "
    "routine operations that are proceeding normally."
)

HEARTBEAT_PROJECT = "summitflow"
HEARTBEAT_MEMORY_GROUP = "summitflow:heartbeat"

# Redis key for last heartbeat timestamp
_REDIS_LAST_RUN_KEY = "persona:heartbeat:last_run"

# Default interval if not set
_DEFAULT_INTERVAL_MINUTES = 60


class HeartbeatResult(BaseModel):
    status: str
    content: str = ""
    turns: int = 0
    tool_calls: int = 0
    interval_minutes: int = _DEFAULT_INTERVAL_MINUTES
    error: str | None = None


async def _resolve_persona(db: Any) -> tuple[str, str, float, str | None, str]:
    """Look up persona agent's model, provider, temperature, thinking_level, and system prompt.

    Returns:
        Tuple of (model, provider, temperature, thinking_level, system_content)
    """
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_routing_utils import inject_agent_mandates
    from app.services.agent_service import get_agent_service

    agent_service = get_agent_service()
    agent = await agent_service.get_by_slug(db, "persona")
    if not agent:
        raise RuntimeError("Persona agent not found in database")
    provider = get_provider_for_model(agent.primary_model_id)

    # Build system prompt with full mode (includes personality, journal, user_context)
    mandate = await inject_agent_mandates(agent, db, prompt_mode="full", project_id=HEARTBEAT_PROJECT)

    return agent.primary_model_id, provider, agent.temperature, agent.thinking_level, mandate.system_content


async def _get_heartbeat_interval() -> tuple[int, bool]:
    """Read heartbeat interval and onboarding status from persona table.

    Returns:
        Tuple of (interval_minutes, onboarding_complete).
    """
    from app.db import async_session
    from app.services.persona_service import get_persona

    async with async_session() as db:
        persona = await get_persona(db)
        if persona:
            return persona.heartbeat_interval_minutes, persona.onboarding_complete
    return _DEFAULT_INTERVAL_MINUTES, False


async def _should_run() -> tuple[bool, int]:
    """Check if enough time has elapsed since the last heartbeat.

    Returns (should_run, interval_minutes).
    Skips if onboarding is not complete (persona shouldn't act autonomously
    before being introduced to the user).
    """
    import redis.asyncio as redis

    from app.config import settings

    interval_minutes, onboarding_complete = await _get_heartbeat_interval()

    # Don't run heartbeat until persona has been onboarded
    if not onboarding_complete:
        return False, interval_minutes

    # 0 = disabled
    if interval_minutes == 0:
        return False, 0

    # Check last run time in Redis
    client = redis.from_url(
        settings.agent_hub_redis_url, encoding="utf-8", decode_responses=True
    )
    try:
        last_run_str = await client.get(_REDIS_LAST_RUN_KEY)
        if not last_run_str:
            return True, interval_minutes

        last_run = datetime.fromisoformat(last_run_str)
        elapsed = (datetime.now(UTC) - last_run).total_seconds() / 60
        return elapsed >= interval_minutes, interval_minutes
    finally:
        await client.close()


async def _record_heartbeat() -> None:
    """Store current timestamp as last heartbeat run."""
    import redis.asyncio as redis

    from app.config import settings

    client = redis.from_url(
        settings.agent_hub_redis_url, encoding="utf-8", decode_responses=True
    )
    try:
        await client.set(_REDIS_LAST_RUN_KEY, datetime.now(UTC).isoformat())
    finally:
        await client.close()


@hatchet.task(
    name="persona-heartbeat",
    input_validator=BaseModel,
    on_crons=["*/5 * * * *"],
    execution_timeout="300s",
    concurrency=ConcurrencyExpression(
        expression="'persona_heartbeat'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def persona_heartbeat_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Periodic persona check-in via complete_internal.

    Checks the configured interval before running. Skips if the last
    heartbeat was too recent or if the heartbeat is disabled (interval=0).
    """
    should_run, interval_minutes = await _should_run()

    if not should_run:
        if interval_minutes == 0:
            reason = "disabled"
        else:
            # Distinguish onboarding vs interval: re-check onboarding status
            _, onboarding_complete = await _get_heartbeat_interval()
            reason = "not onboarded" if not onboarding_complete else "interval not elapsed"
        ctx.log(f"Heartbeat skipped ({reason}, interval={interval_minutes}m)")
        return HeartbeatResult(
            status="skipped",
            interval_minutes=interval_minutes,
        ).model_dump()

    # Check project permission tier — skip if "off"
    from app.db import async_session
    from app.services.project_permission_service import get_project_permission

    async with async_session() as perm_db:
        perm = await get_project_permission(perm_db, HEARTBEAT_PROJECT)
        if perm and perm.permission_tier == "off":
            ctx.log("Heartbeat skipped (project_permission_off)")
            return HeartbeatResult(
                status="skipped",
                interval_minutes=interval_minutes,
            ).model_dump()

    from app.api.complete.core import complete_internal

    async with async_session() as db:
        model, provider, temperature, thinking_level, system_content = await _resolve_persona(db)

        # System prompt built in full mode (includes personality, journal, user_context)
        messages: list[dict[str, Any]] = []
        if system_content:
            messages.append({"role": "system", "content": system_content})
        messages.append({"role": "user", "content": HEARTBEAT_PROMPT})

        result = await complete_internal(
            messages=messages,
            model=model,
            provider=provider,
            temperature=temperature,
            project_id=HEARTBEAT_PROJECT,
            db=db,
            agent_slug="persona",
            use_memory=True,
            memory_group_id=HEARTBEAT_MEMORY_GROUP,
            enable_caching=False,
            skip_cache=True,
            max_turns=7,
            execute_tools=True,
            enable_programmatic_tools=True,
            task_type="heartbeat",
            thinking_level=thinking_level,
        )

    await _record_heartbeat()

    out = HeartbeatResult(
        status=result.status or "success",
        content=result.content[:500] if result.content else "",
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        interval_minutes=interval_minutes,
        error=result.error,
    )
    ctx.log(f"Persona heartbeat: {out.turns} turns, {out.tool_calls} tool calls")
    return out.model_dump()
