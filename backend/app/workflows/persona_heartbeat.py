"""Persona heartbeat — periodic system check via cron.

Cron fires every 5 minutes as a check frequency. The actual heartbeat
interval is configurable via the persona table (default: 60 minutes).
On each tick, the workflow checks if enough time has elapsed since the
last run and skips if not.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel

from app.hatchet_app import hatchet
from app.workflows._heartbeat_postprocess import postprocess_heartbeat
from app.workflows._heartbeat_redis import (
    clear_heartbeat_running,
    record_heartbeat_attempt,
    record_heartbeat_error,
    record_heartbeat_skip,
    set_heartbeat_running,
)
from app.workflows._heartbeat_steps import (
    HEARTBEAT_MEMORY_GROUP,
    HEARTBEAT_PROJECT,
    HeartbeatRuntimeInfo,
    _build_runtime_warning,
    _check_runtime_guards,
    _check_schedule_guards,
    _do_completion,
    _record_completion_outcome,
    _resolve_persona,
    _should_run,
    check_project_permission,
    get_heartbeat_interval,
    get_heartbeat_runtime_info,
    get_persona_execution_state,
)

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_MINUTES = 60

__all__ = [
    "HEARTBEAT_MEMORY_GROUP",
    "HEARTBEAT_PROJECT",
    "HeartbeatInput",
    "HeartbeatResult",
    "HeartbeatRuntimeInfo",
    "_build_runtime_warning",
    "_do_completion",
    "_resolve_persona",
    "_run_persona_heartbeat",
    "_should_run",
    "check_project_permission",
    "create_heartbeat_session_id",
    "get_heartbeat_interval",
    "get_heartbeat_runtime_info",
    "get_persona_execution_state",
]


class HeartbeatInput(BaseModel):
    manual: bool = False
    target_project_id: str | None = None
    heartbeat_session_id: str | None = None
    running_claimed: bool = False
    running_claim_token: str | None = None


class HeartbeatResult(BaseModel):
    status: str
    turns: int = 0
    tool_calls: int = 0
    interval_minutes: int = _DEFAULT_INTERVAL_MINUTES
    error: str | None = None
    format_compliant: bool = True
    summary_stored: bool = False
    mcp_retried: int = 0
    followup_dispatched: bool = False
    followup_reason: str | None = None
    completion_review_used: bool = False
    completion_review_decision: str | None = None
    completion_review_reason: str | None = None
    completion_review_session_id: str | None = None
    completion_review_agent_slug: str | None = None
    completion_review_model_id: str | None = None


def create_heartbeat_session_id() -> str:
    """Return stable UUID string for one heartbeat run."""
    return str(uuid4())


async def _run_persona_heartbeat(input: HeartbeatInput, ctx: Context) -> dict[str, Any]:
    """Periodic persona check-in via complete_internal."""
    from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

    manual = input.manual
    target_project_id = input.target_project_id
    execution_project = target_project_id or HEARTBEAT_PROJECT

    if not manual and not await is_workflow_schedule_enabled("persona_heartbeat"):
        await record_heartbeat_skip("schedule_disabled")
        ctx.log("Heartbeat skipped (schedule disabled)")
        return HeartbeatResult(status="skipped", error="schedule_disabled").model_dump()

    may_proceed, interval_minutes, skip_reason = await _check_schedule_guards(manual)
    if not may_proceed:
        assert skip_reason is not None
        await record_heartbeat_skip(skip_reason)
        ctx.log(f"Heartbeat skipped ({skip_reason}, interval={interval_minutes}m)")
        return HeartbeatResult(status="skipped", interval_minutes=interval_minutes).model_dump()

    runtime_skip = await _check_runtime_guards(target_project_id)
    if runtime_skip:
        await record_heartbeat_skip(runtime_skip)
        ctx.log(f"Heartbeat skipped ({runtime_skip})")
        return HeartbeatResult(status="skipped", interval_minutes=interval_minutes, error=runtime_skip).model_dump()

    heartbeat_session_id = input.heartbeat_session_id or create_heartbeat_session_id()
    running_claim_token = input.running_claim_token
    owns_running_lock = input.running_claimed
    if not input.running_claimed:
        await record_heartbeat_attempt(session_id=heartbeat_session_id)
        running_claim_token = await set_heartbeat_running(
            session_id=heartbeat_session_id,
            trigger="manual" if manual else "cron",
            project_id=execution_project,
            only_if_missing=True,
        )
        if not running_claim_token:
            await record_heartbeat_skip("already_running", session_id=heartbeat_session_id)
            ctx.log("Heartbeat skipped (already_running)")
            return HeartbeatResult(
                status="skipped",
                interval_minutes=interval_minutes,
                error="already_running",
            ).model_dump()
        owns_running_lock = True
    try:
        result, model_review_due = await _do_completion(
            interval_minutes,
            heartbeat_session_id=heartbeat_session_id,
            target_project_id=target_project_id,
        )
        out = await postprocess_heartbeat(result, interval_minutes, target_project_id=target_project_id)
        await _record_completion_outcome(out, heartbeat_session_id, model_review_due)
        ctx.log(f"Persona heartbeat: {out.turns} turns, {out.tool_calls} tool calls")
        return out.model_dump()
    except Exception as e:
        await record_heartbeat_error(str(e), session_id=heartbeat_session_id)
        logger.warning("Heartbeat completion failed: %s", e)
        return HeartbeatResult(
            status="error",
            error=str(e),
            interval_minutes=interval_minutes,
        ).model_dump()
    finally:
        if owns_running_lock:
            await clear_heartbeat_running(
                claim_token=running_claim_token,
                session_id=heartbeat_session_id,
            )


@hatchet.task(
    name="persona-heartbeat",
    input_validator=HeartbeatInput,
    on_crons=["*/5 * * * *"],
    concurrency=ConcurrencyExpression(
        expression="'persona_heartbeat'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def persona_heartbeat_task(input: HeartbeatInput, ctx: Context) -> dict[str, Any]:
    return await _run_persona_heartbeat(input, ctx)
