"""Johnny heartbeat — periodic system check via cron.

Cron fires every 5 minutes as a check frequency. The actual heartbeat
interval is configurable via user preferences (default: 60 minutes).
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
    "Run your regular heartbeat check. Use your tools to assess system health, "
    "check for blocked tasks, review pending work, and inspect quality gate status. "
    "Only send_push if something genuinely needs human attention — don't push for "
    "routine operations that are proceeding normally. Summarize what you found."
)

HEARTBEAT_PROJECT = "summitflow"
HEARTBEAT_MEMORY_GROUP = "summitflow:heartbeat"

# Redis key for last heartbeat timestamp
_REDIS_LAST_RUN_KEY = "johnny:heartbeat:last_run"

# Default interval if not set in preferences
_DEFAULT_INTERVAL_MINUTES = 60


class HeartbeatResult(BaseModel):
    status: str
    content: str = ""
    turns: int = 0
    tool_calls: int = 0
    interval_minutes: int = _DEFAULT_INTERVAL_MINUTES
    error: str | None = None


async def _resolve_johnny(db: Any) -> tuple[str, str, float]:
    """Look up Johnny's model, provider, and temperature from DB."""
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_service import get_agent_service

    agent_service = get_agent_service()
    agent = await agent_service.get_by_slug(db, "johnny")
    if not agent:
        raise RuntimeError("Johnny agent not found in database")
    provider = get_provider_for_model(agent.primary_model_id)
    return agent.primary_model_id, provider, agent.temperature


async def _should_run() -> tuple[bool, int]:
    """Check if enough time has elapsed since the last heartbeat.

    Returns (should_run, interval_minutes).
    """
    import redis.asyncio as redis

    from app.api.preferences import get_preference_value
    from app.config import settings
    from app.db import async_session

    # Read configured interval from preferences
    async with async_session() as db:
        interval_str = await get_preference_value(
            db, "heartbeat_interval_minutes", str(_DEFAULT_INTERVAL_MINUTES)
        )
    interval_minutes = int(interval_str)

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
    name="johnny-heartbeat",
    input_validator=BaseModel,
    on_crons=["*/5 * * * *"],
    execution_timeout="300s",
    concurrency=ConcurrencyExpression(
        expression="'johnny_heartbeat'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def johnny_heartbeat_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Periodic Johnny check-in via complete_internal.

    Checks the configured interval before running. Skips if the last
    heartbeat was too recent or if the heartbeat is disabled (interval=0).
    """
    should_run, interval_minutes = await _should_run()

    if not should_run:
        reason = "disabled" if interval_minutes == 0 else "interval not elapsed"
        ctx.log(f"Heartbeat skipped ({reason}, interval={interval_minutes}m)")
        return HeartbeatResult(
            status="skipped",
            interval_minutes=interval_minutes,
        ).model_dump()

    from app.api.complete.core import complete_internal
    from app.db import async_session

    async with async_session() as db:
        model, provider, temperature = await _resolve_johnny(db)

        result = await complete_internal(
            messages=[{"role": "user", "content": HEARTBEAT_PROMPT}],
            model=model,
            provider=provider,
            temperature=temperature,
            project_id=HEARTBEAT_PROJECT,
            db=db,
            agent_slug="johnny",
            use_memory=True,
            memory_group_id=HEARTBEAT_MEMORY_GROUP,
            enable_caching=False,
            skip_cache=True,
            max_turns=7,
            execute_tools=True,
            enable_programmatic_tools=True,
            task_type="heartbeat",
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
    ctx.log(f"Johnny heartbeat: {out.turns} turns, {out.tool_calls} tool calls")
    return out.model_dump()
