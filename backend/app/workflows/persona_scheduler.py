"""Persona scheduler — execute due scheduled jobs every minute.

Polls persona_scheduled_jobs for enabled jobs with next_run_at <= now(),
executes each one (agent_turn or push), updates run tracking, and
computes the next run time.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel

from app.db import async_session
from app.hatchet_app import hatchet
from app.services.telegram_config_service import load_runtime_config
from app.services.telegram_delivery import send_rendered_message

logger = logging.getLogger(__name__)

# Project / memory constants
SCHEDULER_PROJECT = "agent-hub"
SCHEDULER_MEMORY_GROUP = "project:agent-hub"

# Payload type constants
PAYLOAD_TYPE_AGENT_TURN = "agent_turn"
PAYLOAD_TYPE_PUSH = "push"
PAYLOAD_TYPE_SELF_HONING = "self_honing"
PAYLOAD_TYPE_MEMORY_REVIEW = "memory_review"

# Misc string constants
DELIVERY_PUSH = "push"
DELIVERY_TELEGRAM = "telegram"
PERMISSION_TIER_OFF = "off"

# Self-honing configuration
_SELF_HONING_AGENT_SLUGS = frozenset({"persona", "supervisor"})
_SELF_HONING_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "persona-scheduled-honing"
_SELF_HONING_TIMEOUT_SECONDS: float | None = None
_SELF_HONING_RUNS_PER_CASE = 2
_SELF_HONING_REVIEWER_RUNS_PER_CASE = 1
_SELF_HONING_MAX_ITERATIONS = 2
_SELF_HONING_COHORT_REPETITIONS = 2


async def query_active_sessions(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Lazily import active-session lookup for patchable scheduler tests."""
    from app.services.memory.continuity_query import query_active_sessions as _impl

    return await _impl(*args, **kwargs)


async def run_honing_loop(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Lazily import the honing loop so tests can patch the scheduler seam."""
    from scripts.run_persona_honing_loop import run_honing_loop as _impl

    return await _impl(*args, **kwargs)


class SchedulerResult(BaseModel):
    status: str
    jobs_executed: int = 0
    errors: list[str] | None = None


class JobExecutionResult(BaseModel):
    output: str
    session_id: str | None = None


def compute_next_run(
    schedule_type: str,
    schedule_value: str,
    timezone: str = "UTC",
    last_run_at: datetime | None = None,
) -> datetime | None:
    """Compute the next run time for a scheduled job.

    Args:
        schedule_type: "at", "every", or "cron"
        schedule_value: ISO datetime, interval in ms, or cron expression
        timezone: IANA timezone string
        last_run_at: When the job last ran (None if never)

    Returns:
        Next run datetime (UTC), or None for completed one-shots.
    """
    now = datetime.now(UTC)

    if schedule_type == "at":
        target = datetime.fromisoformat(schedule_value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        return target if target > now else None

    if schedule_type == "every":
        interval = timedelta(milliseconds=int(schedule_value))
        base = last_run_at if last_run_at else now
        next_time = base + interval
        if next_time <= now:
            next_time = now + interval
        return next_time

    if schedule_type == "cron":
        import zoneinfo

        from croniter import croniter

        try:
            tz = zoneinfo.ZoneInfo(timezone)
        except Exception:
            logger.debug("Invalid timezone %r, falling back to UTC", timezone, exc_info=True)
            tz = zoneinfo.ZoneInfo("UTC")
        base = (last_run_at or now).astimezone(tz)
        return croniter(schedule_value, base).get_next(datetime).astimezone(UTC)

    return None


async def _check_project_permission() -> str | None:
    """Return a skip reason if the scheduler project permission is off, else None."""
    from app.db import async_session
    from app.services.project_permission_service import get_project_permission

    async with async_session() as perm_db:
        perm = await get_project_permission(perm_db, SCHEDULER_PROJECT)
        if perm and perm.permission_tier == PERMISSION_TIER_OFF:
            return "Skipped: project permission tier is off"
    return None


async def _execute_agent_turn(job: Any) -> JobExecutionResult:
    """Execute a scheduled job as an agent turn via complete_internal."""
    from app.api.complete.core import complete_internal
    from app.db import async_session
    from app.services._persona_crud import get_persona_limit
    from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent
    from app.services.persona_service import get_persona

    skip = await _check_project_permission()
    if skip:
        return JobExecutionResult(output=skip)

    async with async_session() as db:
        resolved = await resolve_agent("persona", db)
        agent = resolved.agent
        provider = resolved.provider
        mandate = await inject_agent_mandates(
            agent, db, prompt_mode="full", project_id=SCHEDULER_PROJECT, task_type="scheduled_job"
        )
        max_turns = get_persona_limit(await get_persona(db), "max_turns")

        messages: list[dict[str, Any]] = []
        if mandate.system_content:
            messages.append({"role": "system", "content": mandate.system_content})
        messages.append({"role": "user", "content": job.payload_message})

        result = await complete_internal(
            messages=messages,
            model=resolved.model,
            provider=provider,
            temperature=agent.temperature,
            project_id=SCHEDULER_PROJECT,
            db=db,
            agent_slug="persona",
            use_memory=True,
            memory_group_id=SCHEDULER_MEMORY_GROUP,
            enable_caching=False,
            skip_cache=True,
            max_turns=max_turns,
            execute_tools=True,
            enable_programmatic_tools=True,
            defer_tool_loading=True,
            task_type="scheduled_job",
            thinking_level=agent.thinking_level,
        )
        return JobExecutionResult(
            output=result.content[:500] if result.content else "(no output)",
            session_id=result.session_id,
        )


async def _execute_push(job: Any) -> JobExecutionResult:
    """Execute a scheduled job as a push notification."""
    from app.db import async_session
    from app.services.push_service import send_push

    payload: dict[str, str] = {
        "title": job.payload_title or job.name,
        "body": job.payload_message,
    }
    async with async_session() as db:
        sent = await send_push(db, payload=payload)
    return JobExecutionResult(output=f"Push sent to {sent} device(s)")


def _scheduled_self_honing_paths(now: datetime | None = None) -> tuple[Path, Path, Path]:
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    run_root = _SELF_HONING_ROOT / timestamp
    return run_root / "work", run_root / "reports", run_root / "result.json"


async def _resolve_self_honing_models() -> tuple[list[str], list[str]]:
    from app.db import async_session
    from app.services.agent_routing_utils import resolve_agent

    async with async_session() as db:
        persona = await resolve_agent("persona", db)
        try:
            supervisor = await resolve_agent("supervisor", db)
        except Exception:
            supervisor = None

    reviewer_models = [supervisor.model] if supervisor else []
    return [persona.model], reviewer_models


async def _active_self_honing_conflicts() -> list[dict[str, Any]]:
    from app.db import async_session

    async with async_session() as db:
        sessions = await query_active_sessions(db, max_entries=20)
    return [s for s in sessions if str(s.get("agent_slug") or "") in _SELF_HONING_AGENT_SLUGS]


async def _execute_self_honing(job: Any) -> JobExecutionResult:
    from app.services.persona_improvement import PERSONA_IMPROVEMENT_SUITE_ID
    from scripts.completion_review_benchmark_cases import get_default_completion_review_case_ids
    from scripts.persona_benchmark_cases import get_persona_improvement_case_ids

    conflicts = await _active_self_honing_conflicts()
    if conflicts:
        active = ", ".join(
            f"{item.get('agent_slug')}:{str(item.get('session_id') or '')[:8]}"
            for item in conflicts
        )
        return JobExecutionResult(output=f"Skipped: active self-edit conflict sessions present ({active})")

    models, reviewer_models = await _resolve_self_honing_models()
    working_root, output_dir, output_json_path = _scheduled_self_honing_paths()
    seed = int(datetime.now(UTC).strftime("%Y%m%d"))
    reviewer_case_ids = get_default_completion_review_case_ids() if reviewer_models else None

    result = await run_honing_loop(
        models=models,
        case_ids=get_persona_improvement_case_ids(),
        runs_per_case=_SELF_HONING_RUNS_PER_CASE,
        reviewer_models=reviewer_models or None,
        reviewer_case_ids=reviewer_case_ids,
        reviewer_runs_per_case=_SELF_HONING_REVIEWER_RUNS_PER_CASE,
        project_id=SCHEDULER_PROJECT,
        working_root=working_root,
        output_dir=output_dir,
        seed=seed,
        timeout_seconds=_SELF_HONING_TIMEOUT_SECONDS,
        client_id=None,
        use_memory=True,
        benchmark_task_type="heartbeat",
        max_iterations=_SELF_HONING_MAX_ITERATIONS,
        cohort_repetitions=_SELF_HONING_COHORT_REPETITIONS,
        base_url="http://localhost:8003",
        output_json_path=output_json_path,
        suite_id=PERSONA_IMPROVEMENT_SUITE_ID,
        agent_slug="persona",
        persist_results=True,
        disable_completion_review=not bool(reviewer_models),
    )

    iterations = result.get("iterations") or []
    latest_benchmark_id = iterations[-1].get("benchmark_id") if iterations else "n/a"
    latest_decision = iterations[-1].get("final_decision") if iterations else "n/a"
    return JobExecutionResult(
        output=(
            "Self-honing completed: "
            f"honed={result.get('honed')} "
            f"iterations={result.get('completed_iterations')} "
            f"decision={latest_decision} "
            f"benchmark_id={latest_benchmark_id} "
            f"output={output_json_path}"
        )
    )


def _parse_memory_review_payload(payload_message: str) -> dict[str, Any]:
    """Parse optional JSON config for a scheduled memory review job."""
    try:
        parsed = json.loads(payload_message)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def _execute_memory_review(job: Any) -> JobExecutionResult:
    """Execute one rolling memory-review batch."""
    from app.db import async_session
    from app.services.memory.review_agent import (
        DEFAULT_BATCH_LIMIT,
        DEFAULT_REVIEW_CADENCE_DAYS,
        DEFAULT_REVIEWER_AGENT,
        run_memory_review_batch,
    )

    payload = _parse_memory_review_payload(job.payload_message or "")
    batch_limit = max(1, min(int(payload.get("batch_limit") or DEFAULT_BATCH_LIMIT), DEFAULT_BATCH_LIMIT))
    cadence_days = int(payload.get("cadence_days") or DEFAULT_REVIEW_CADENCE_DAYS)
    reviewer_agent_slug = str(payload.get("reviewer_agent_slug") or DEFAULT_REVIEWER_AGENT)
    reviewer_model_id = payload.get("reviewer_model_id")
    reviewer_model_id = str(reviewer_model_id) if reviewer_model_id else None
    dry_run = bool(payload.get("dry_run") or False)
    force_all = bool(payload.get("force_all") or False)
    include_archived = bool(payload.get("include_archived") or False)
    only_missing_compact = bool(payload.get("only_missing_compact") or False)
    only_incomplete_audit = bool(payload.get("only_incomplete_audit") or False)

    async with async_session() as db:
        result = await run_memory_review_batch(
            db=db,
            batch_limit=batch_limit,
            cadence_days=cadence_days,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=reviewer_model_id,
            dry_run=dry_run,
            force_all=force_all,
            include_archived=include_archived,
            only_missing_compact=only_missing_compact,
            only_incomplete_audit=only_incomplete_audit,
        )
        await db.commit()

    return JobExecutionResult(
        output=(
            "Memory review "
            f"{result.status}: reviewed={result.reviewed_count} "
            f"needs_action={result.needs_action_count} failed={result.failed_count} "
            f"reviewer={result.reviewer_agent_slug} model={result.reviewer_model_id or 'n/a'} "
            f"run={result.run_id or 'n/a'}"
        ),
        session_id=result.session_id,
    )


async def execute_job(job: Any) -> JobExecutionResult:
    """Dispatch to the correct executor based on payload type."""
    if job.payload_type == PAYLOAD_TYPE_PUSH:
        return await _execute_push(job)
    if job.payload_type == PAYLOAD_TYPE_SELF_HONING:
        return await _execute_self_honing(job)
    if job.payload_type == PAYLOAD_TYPE_MEMORY_REVIEW:
        return await _execute_memory_review(job)
    return await _execute_agent_turn(job)


async def _maybe_send_delivery_push(job: Any, output: str) -> None:
    """Send a post-execution push notification if the job is configured for it."""
    if job.delivery != DELIVERY_PUSH or job.payload_type != PAYLOAD_TYPE_AGENT_TURN:
        return
    try:
        from app.db import async_session
        from app.services.push_service import send_push

        async with async_session() as push_db:
            await send_push(push_db, payload={
                "title": f"Scheduled: {job.name}",
                "body": output[:200],
                "tag": f"scheduled:{job.id}",
            })
    except Exception:
        logger.debug("Delivery push failed for job %s", job.id)


async def _maybe_send_delivery_telegram(job: Any, output: str) -> None:
    """Send a post-execution Telegram notification if the job is configured for it."""
    if job.delivery != DELIVERY_TELEGRAM:
        return
    if job.payload_type != PAYLOAD_TYPE_AGENT_TURN:
        logger.warning(
            "Telegram delivery skipped for job %s (%s): unsupported payload_type=%s",
            job.id,
            job.name,
            job.payload_type,
        )
        return
    try:
        async with async_session() as db:
            runtime_config = await load_runtime_config(db)
        token = runtime_config.get("token")
        report_chat_id = runtime_config.get("report_chat_id")
        if not token or not report_chat_id:
            missing = []
            if not token:
                missing.append("bot_token")
            if not report_chat_id:
                missing.append("report_chat_id")
            logger.warning(
                "Telegram delivery skipped for job %s (%s): missing config: %s",
                job.id,
                job.name,
                ", ".join(missing),
            )
            return
        from telegram import Bot

        bot = Bot(token=token)
        await send_rendered_message(
            bot=bot,
            chat_id=str(report_chat_id),
            text=output,
            disable_link_previews=True,
        )
    except Exception as exc:
        logger.warning(
            "Telegram delivery failed for job %s (%s): %s",
            job.id,
            job.name,
            exc,
        )


def _update_job_state(job: Any, now: datetime) -> None:
    """Update run tracking fields and compute the next scheduled run time."""
    job.last_run_at = now
    job.run_count += 1
    job.next_run_at = compute_next_run(
        job.schedule_type, job.schedule_value, job.schedule_timezone, now
    )
    if job.max_runs is not None and job.run_count >= job.max_runs:
        job.enabled = False


@hatchet.task(
    name="persona-scheduler",
    input_validator=BaseModel,
    on_crons=["*/5 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'persona_scheduler'",
        max_runs=1,
        # Scheduler jobs can invoke full persona completions that exceed one minute.
        # Drop overlapping cron ticks instead of cancelling live persona work mid-run.
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def persona_scheduler_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Poll and execute due scheduled jobs."""
    from sqlalchemy import select

    from app.db import async_session
    from app.models.persona_scheduled_job import PersonaScheduledJob
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

    errors: list[str] = []
    executed = 0

    if not await is_workflow_schedule_enabled("persona_scheduler"):
        ctx.log("Persona scheduler skipped (schedule disabled)")
        return SchedulerResult(status="disabled").model_dump()

    async with async_session() as db:
        now = datetime.now(UTC)
        result = await db.execute(
            select(PersonaScheduledJob).where(
                PersonaScheduledJob.enabled.is_(True),
                PersonaScheduledJob.next_run_at <= now,
            )
        )
        jobs = result.scalars().all()

        if not jobs:
            return SchedulerResult(status="idle").model_dump()

        for job in jobs:
            try:
                result = await execute_job(job)
                await _maybe_send_delivery_push(job, result.output)
                await _maybe_send_delivery_telegram(job, result.output)
                _update_job_state(job, now)
                executed += 1
                logger.info("Scheduled job %s (%s) executed", job.name, job.id)
            except Exception as e:
                logger.exception("Scheduled job %s failed", job.id)
                errors.append(f"{job.name}: {e}")

        await db.commit()

    ctx.log(f"Scheduler: {executed} jobs executed, {len(errors)} errors")
    return SchedulerResult(
        status="executed" if executed else "idle",
        jobs_executed=executed,
        errors=errors or None,
    ).model_dump()
