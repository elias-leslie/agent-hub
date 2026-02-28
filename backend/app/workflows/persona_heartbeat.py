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
from app.services.tools.direct_executor_core import KNOWN_ROOTS

logger = logging.getLogger(__name__)

_HEARTBEAT_PROMPT_TEMPLATE = """\
Run your regular heartbeat check. Current time: {timestamp} ({local_time})

{project_access_summary}

## Your Role: Orchestrator

You are a **coordinator of specialist agents**, not a solo executor. Use this \
two-tier dispatch system for every action:

### Do it yourself + journal (no task needed)
Work that only uses your persona tools and doesn't touch project code:
- Resolve/triage feedback (`st feedback resolve`, create tasks from feedback)
- Tag/untag memories, run `st memory cleanup`
- Update user_context, personality, or heartbeat_instructions
- Answer consultations, curate journal entries
- Quick CLI checks (`st health`, `st ready`)

### Create task + dispatch (anything touching code)
1. **Needs specialist** → `consult_agent` (coder, fixer, reviewer, tester)
2. **Multi-step / needs verification** → `manage_tasks(action=create)` then \
`manage_tasks(action=dispatch)` to send it through autocode
3. **Needs human** → `manage_tasks(action=create)` + `send_push`

**Rule of thumb**: If it touches project code or git → create a task. \
If it only uses your persona tools → just do it and journal what you did. \
You can only execute code in projects with YOLO + auto-exec (see access above). \
For read-only projects, you can observe and create tasks but cannot execute.

## 1. Situational Awareness (parallel calls)
- `manage_tasks(action=list_ready)` — pending/blocked tasks
- `list_consultations` — any needing attention
- `list_scheduled_jobs` — scheduled work status
- `read_journal(days_back=7)` — your recent observations

## 2. Review Your Dispatched Work
Before creating NEW work, check on work you already dispatched:
- **Completed tasks you created?** Review the results — did they land well? \
Create follow-up tasks if the result needs refinement or has issues.
- **In-progress tasks?** Check if they're stuck, failed, or need help.
- **Failed dispatches?** Diagnose why — wrong approach? Bad instructions? \
Create a better-scoped follow-up task.
- Track your dispatch history in your journal so you maintain continuity.

## 3. Act on What You Find
- **Blocked task you can unblock?** Dispatch it or consult a specialist agent.
- **Stale task nobody's touched?** Dispatch via `manage_tasks(action=dispatch)`.
- **Feedback items actionable?** Create tasks from `st feedback list`.
- **Quality issue in recent commits?** Create a task and dispatch a fixer.
- **Repeating failure pattern?** Create an improvement task.
- If nothing needs action, that's fine — skip to step 5.

## 4. Model Review ({model_review_status})
{model_review_instructions}

## 5. Proactive Creative Work (pick ONE — this is your main value)
You are not a janitor. You are a **creative autonomous agent** who makes projects \
better in ways nobody asked for. Scan a YOLO + auto-exec project and imagine \
what would make it genuinely better:

- **New features**: What's missing? What would delight a user? What's the obvious \
next feature nobody's built yet?
- **Design & UX**: Is the UI generic? Could interactions be smoother? Are there \
dead-end flows or confusing states?
- **Game feel** (monkey-fight): New enemy types, visual effects, sound design, \
level variety, scoring mechanics, power-ups, juice
- **Developer experience**: Missing CLI commands, slow workflows, missing dashboards
- **Performance & polish**: Loading states, error recovery, animations, responsiveness
- **Architecture**: Patterns worth extracting, abstractions that would unlock new features

**Think like a product owner**, not a maintenance engineer. Ask: "If I were a user, \
what would make me go 'oh that's cool'?" Then create the task and dispatch it.

**How to act:**
1. Read recent git log + browse key files to understand current state
2. Identify the most impactful creative improvement
3. `manage_tasks(action=create)` with a clear description of WHAT and WHY
4. `manage_tasks(action=dispatch)` to send it through autocode
5. Journal what you envisioned and dispatched

**You MUST attempt proactive work every heartbeat.** Don't bail with "nothing to \
report." If you genuinely can't find anything (unlikely), explain what you looked at \
and why nothing was worth doing.

## 6. Background Maintenance (only if step 5 is done)
Memory hygiene, feedback triage, journal curation — but only AFTER creative work.

## 7. Journal
Call `write_journal` with a concise observation summarizing what you found \
and any actions taken. Skip if literally nothing happened.

## Rules
- Only `send_push` if something genuinely needs human attention.
- Don't push for routine "all clear" status.
- Prefer batching actions into this heartbeat over creating scheduled jobs.
- **NEVER claim you have access you don't** — check the project list above.
- **Concurrency limit**: Only dispatch ONE new task per heartbeat. Finish reviewing \
existing dispatched work first. If you have 3+ tasks in-progress that you created, \
focus on reviewing those instead of creating more. Quality over quantity — one \
well-scoped, well-described task beats five vague ones.\
"""

_MODEL_REVIEW_DO = (
    "Due — run `review_agent_performance` + `manage_model_config(action=get_benchmarks)` + "
    "`manage_model_config(action=list_agents)`. Check `synced_at` — if benchmark data >60 days old, "
    "`send_push` to flag stale benchmarks. Evaluate model assignments. Log via `log_agent_performance`."
)
_MODEL_REVIEW_SKIP = "Not due — skip model review this heartbeat."

HEARTBEAT_PROJECT = "summitflow"
HEARTBEAT_MEMORY_GROUP = "summitflow:heartbeat"

# Redis keys for heartbeat state
_REDIS_LAST_RUN_KEY = "persona:heartbeat:last_run"
_REDIS_LAST_MODEL_REVIEW_KEY = "persona:heartbeat:last_model_review"

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


async def _record_heartbeat(did_model_review: bool = False) -> None:
    """Store current timestamp as last heartbeat run (and model review if done)."""
    import redis.asyncio as redis

    from app.config import settings

    client = redis.from_url(
        settings.agent_hub_redis_url, encoding="utf-8", decode_responses=True
    )
    try:
        now = datetime.now(UTC).isoformat()
        await client.set(_REDIS_LAST_RUN_KEY, now)
        if did_model_review:
            await client.set(_REDIS_LAST_MODEL_REVIEW_KEY, now)
    finally:
        await client.close()


async def _get_model_review_status() -> tuple[bool, str]:
    """Check if a model review is due (>7 days since last one).

    Returns (is_due, status_label).
    """
    import redis.asyncio as redis

    from app.config import settings

    client = redis.from_url(
        settings.agent_hub_redis_url, encoding="utf-8", decode_responses=True
    )
    try:
        last_review_str = await client.get(_REDIS_LAST_MODEL_REVIEW_KEY)
        if not last_review_str:
            return True, "never reviewed"
        last_review = datetime.fromisoformat(last_review_str)
        days_ago = (datetime.now(UTC) - last_review).total_seconds() / 86400
        if days_ago >= 7:
            return True, f"last review {days_ago:.0f} days ago"
        return False, f"last review {days_ago:.1f} days ago"
    finally:
        await client.close()


async def _get_project_access_summary() -> str:
    """Build a summary of project access tiers for the heartbeat prompt."""
    from sqlalchemy import text

    from app.db import async_session

    try:
        async with async_session() as db:
            result = await db.execute(
                text("SELECT project_id, permission_tier, auto_exec_enabled FROM project_permissions ORDER BY project_id")
            )
            rows = result.fetchall()

        if not rows:
            return "Your project access: (no projects configured)"

        lines = ["Your project access:"]
        for row in rows:
            tier = row.permission_tier
            auto = "auto-exec" if row.auto_exec_enabled else "manual"
            lines.append(f"- {row.project_id}: {tier} ({auto})")
        return "\n".join(lines)
    except Exception:
        logger.exception("Failed to fetch project access summary")
        return "Your project access: (unavailable)"


async def _build_heartbeat_prompt(model_review_due: bool, model_review_label: str) -> str:
    """Build the heartbeat prompt with dynamic model review instructions and project access."""
    from zoneinfo import ZoneInfo

    project_access = await _get_project_access_summary()
    now_utc = datetime.now(UTC)
    # Pre-compute local time so the persona doesn't waste tokens on timezone math
    local_tz = ZoneInfo("America/New_York")
    local_time = now_utc.astimezone(local_tz).strftime("%H:%M %Z")

    return _HEARTBEAT_PROMPT_TEMPLATE.format(
        timestamp=now_utc.strftime("%Y-%m-%d %H:%M UTC"),
        local_time=local_time,
        project_access_summary=project_access,
        model_review_status="DUE" if model_review_due else f"not due — {model_review_label}",
        model_review_instructions=_MODEL_REVIEW_DO if model_review_due else _MODEL_REVIEW_SKIP,
    )


@hatchet.task(
    name="persona-heartbeat",
    input_validator=BaseModel,
    on_crons=["*/5 * * * *"],
    execution_timeout="600s",
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

    model_review_due, model_review_label = await _get_model_review_status()
    heartbeat_prompt = await _build_heartbeat_prompt(model_review_due, model_review_label)

    async with async_session() as db:
        model, provider, temperature, thinking_level, system_content = await _resolve_persona(db)

        # System prompt built in full mode (includes personality, journal, user_context)
        messages: list[dict[str, Any]] = []
        if system_content:
            messages.append({"role": "system", "content": system_content})
        messages.append({"role": "user", "content": heartbeat_prompt})

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
            max_turns=25,
            execute_tools=True,
            enable_programmatic_tools=True,
            task_type="heartbeat",
            thinking_level=thinking_level,
            working_dir=KNOWN_ROOTS.get(HEARTBEAT_PROJECT),
        )

    await _record_heartbeat(did_model_review=model_review_due)

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
