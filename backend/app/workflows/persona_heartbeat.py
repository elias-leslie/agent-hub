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
from app.services.tools.direct_executor_core import KNOWN_ROOTS
from app.workflows._heartbeat_postprocess import postprocess_heartbeat
from app.workflows._heartbeat_prompt import (
    build_heartbeat_prompt,
)
from app.workflows._heartbeat_redis import (
    check_redis_elapsed,
    clear_heartbeat_running,
    get_model_review_status,
    record_heartbeat_attempt,
    record_heartbeat_error,
    record_heartbeat_skip,
    record_heartbeat_success,
    set_heartbeat_running,
)

logger = logging.getLogger(__name__)

HEARTBEAT_PROJECT = "persona-sandbox"
HEARTBEAT_MEMORY_GROUP = "project:persona-sandbox"
_DEFAULT_INTERVAL_MINUTES = 60


class HeartbeatInput(BaseModel):
    manual: bool = False
    target_project_id: str | None = None


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


class HeartbeatRuntimeInfo(BaseModel):
    """Resolved persona heartbeat runtime and compatibility state."""

    model: str
    provider: str
    model_display_name: str | None = None
    thinking_level: str | None = None
    supports_tools: bool
    supports_thinking: bool
    supports_verbosity: bool
    supports_session_cache: bool
    heartbeat_supported: bool
    warnings: list[str] = []


async def _resolve_persona(
    db: Any,
    project_id: str = HEARTBEAT_PROJECT,
) -> tuple[str, str, float, str | None, str, dict[str, Any] | None]:
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
        agent, db, prompt_mode="full", project_id=project_id, task_type="heartbeat"
    )
    return agent.primary_model_id, provider, agent.temperature, agent.thinking_level, mandate.system_content, agent.memory_config


def _build_runtime_warning(model: str) -> str:
    return f"Heartbeat requires tool execution, but {model} does not support tools."


async def get_heartbeat_runtime_info() -> HeartbeatRuntimeInfo:
    """Return the resolved model/provider and whether heartbeat can run on it."""
    from app.adapters.registry import supports_thinking, supports_tools
    from app.constants.catalog import get_model_capabilities, get_model_entry
    from app.db import async_session

    async with async_session() as db:
        model, provider, _, thinking_level, _, _ = await _resolve_persona(db)

    capabilities = get_model_capabilities(model)
    entry = get_model_entry(model)
    tool_support = supports_tools(provider, model)
    thinking_support = supports_thinking(provider, model)

    warnings: list[str] = []
    if not tool_support:
        warnings.append(_build_runtime_warning(model))

    return HeartbeatRuntimeInfo(
        model=model,
        provider=provider,
        model_display_name=entry.name if entry else None,
        thinking_level=thinking_level,
        supports_tools=tool_support,
        supports_thinking=thinking_support,
        supports_verbosity=bool(capabilities and capabilities.supports_verbosity),
        supports_session_cache=bool(capabilities and capabilities.supports_session_cache),
        heartbeat_supported=tool_support,
        warnings=warnings,
    )


async def get_heartbeat_interval() -> tuple[int, bool]:
    """Return (interval_minutes, onboarding_complete) from the persona table."""
    from app.db import async_session
    from app.services.persona_service import get_persona

    async with async_session() as db:
        persona = await get_persona(db)
        if persona:
            return persona.heartbeat_interval_minutes, persona.onboarding_complete
    return _DEFAULT_INTERVAL_MINUTES, False


async def get_persona_execution_state() -> str:
    """Return the current persona execution state."""
    from app.db import async_session
    from app.services.persona_service import get_persona

    async with async_session() as db:
        persona = await get_persona(db)
        if persona and getattr(persona, "execution_state", None):
            return str(persona.execution_state)
    return "active"


async def _should_run() -> tuple[bool, int, bool, str]:
    """Return (should_run, interval_minutes, onboarding_complete, execution_state) based on schedule.

    Skips if onboarding is not complete or if heartbeat is disabled.
    """
    interval_minutes, onboarding_complete = await get_heartbeat_interval()
    execution_state = await get_persona_execution_state()

    if not onboarding_complete:
        return False, interval_minutes, onboarding_complete, execution_state
    if execution_state == "paused":
        return False, interval_minutes, onboarding_complete, execution_state
    if interval_minutes == 0:
        return False, 0, onboarding_complete, execution_state

    elapsed = await check_redis_elapsed(interval_minutes)
    return elapsed, interval_minutes, onboarding_complete, execution_state


def _get_skip_reason(interval_minutes: int, onboarding_complete: bool, execution_state: str = "active") -> str:
    """Return a human-readable reason the heartbeat was skipped."""
    if execution_state == "paused":
        return "paused"
    if interval_minutes == 0:
        return "disabled"
    return "not onboarded" if not onboarding_complete else "interval not elapsed"


async def check_project_permission(project_id: str = HEARTBEAT_PROJECT) -> bool:
    """Return False if the target project permission_tier is 'off'."""
    from app.db import async_session
    from app.services.project_permission_service import get_project_permission

    async with async_session() as perm_db:
        perm = await get_project_permission(perm_db, project_id)
        return not (perm and perm.permission_tier == "off")


def _build_messages(system_content: str, prompt: str) -> list[dict[str, Any]]:
    """Assemble the messages list for complete_internal."""
    messages: list[dict[str, Any]] = []
    if system_content:
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": prompt})
    return messages


async def _execute_heartbeat(
    interval_minutes: int,
    *,
    heartbeat_session_id: str,
    target_project_id: str | None = None,
) -> HeartbeatResult:
    """Run completion and record result; returns a HeartbeatResult."""
    try:
        result = await _do_completion(
            interval_minutes,
            heartbeat_session_id=heartbeat_session_id,
            target_project_id=target_project_id,
        )
    except Exception as e:
        logger.warning("Heartbeat completion failed: %s", e)
        return HeartbeatResult(
            status="error", error=str(e), interval_minutes=interval_minutes
        )
    return await postprocess_heartbeat(result, interval_minutes, target_project_id=target_project_id)


async def _resolve_completion_context(
    execution_project: str,
) -> tuple[str, str, float, str | None, str, dict[str, Any] | None, int]:
    """Resolve persona agent config and max_turns for a heartbeat completion."""
    from app.db import async_session
    from app.services._persona_crud import get_persona_limit
    from app.services.persona_service import get_persona

    async with async_session() as db:
        model, provider, temperature, thinking_level, system_content, agent_memory_config = await _resolve_persona(
            db, project_id=execution_project,
        )
        persona = await get_persona(db)
        max_turns = get_persona_limit(persona, "max_turns")
    return model, provider, temperature, thinking_level, system_content, agent_memory_config, max_turns


async def _do_completion(
    interval_minutes: int,
    *,
    heartbeat_session_id: str,
    target_project_id: str | None = None,
):
    """Run the actual completion call — separated for error handling."""
    from app.api.complete.core import complete_internal
    from app.db import async_session

    model_review_due, model_review_label = await get_model_review_status()
    execution_project = target_project_id or HEARTBEAT_PROJECT

    model, provider, temperature, thinking_level, system_content, agent_memory_config, max_turns = (
        await _resolve_completion_context(execution_project)
    )
    heartbeat_prompt = await build_heartbeat_prompt(
        model_review_due,
        model_review_label,
        target_project_id=target_project_id,
        provider=provider,
    )
    async with async_session() as db:
        result = await complete_internal(
            messages=_build_messages(system_content, heartbeat_prompt),
            model=model,
            provider=provider,
            temperature=temperature,
            project_id=execution_project,
            db=db,
            session_id=heartbeat_session_id,
            agent_slug="persona",
            request_source="heartbeat",
            use_memory=True,
            memory_group_id=HEARTBEAT_MEMORY_GROUP,
            memory_config=agent_memory_config,
            enable_caching=False,
            skip_cache=True,
            max_turns=max_turns,
            execute_tools=True,
            enable_programmatic_tools=True,
            defer_tool_loading=True,
            task_type="heartbeat",
            thinking_level=thinking_level,
            working_dir=KNOWN_ROOTS.get(execution_project),
            requested_model=model,
            requested_provider=provider,
        )

    return result, model_review_due


async def _check_schedule_guards(manual: bool) -> tuple[bool, int, str | None]:
    """Check schedule and onboarding guards, returning (may_proceed, interval_minutes, skip_reason).

    Returns skip_reason=None when the heartbeat should proceed.
    """
    if not manual:
        should_run, interval_minutes, onboarding_complete, execution_state = await _should_run()
        if not should_run:
            return False, interval_minutes, _get_skip_reason(interval_minutes, onboarding_complete, execution_state)
        return True, interval_minutes, None

    interval_minutes, onboarding_complete = await get_heartbeat_interval()
    execution_state = await get_persona_execution_state()
    if not onboarding_complete:
        return False, interval_minutes, "not onboarded"
    if execution_state == "paused":
        return False, interval_minutes, "paused"
    return True, interval_minutes, None


async def _check_runtime_guards(
    target_project_id: str | None,
) -> str | None:
    """Return a skip reason if permissions or runtime prevent execution, else None."""
    if not await check_project_permission(target_project_id or HEARTBEAT_PROJECT):
        return "project_permission_off"
    runtime = await get_heartbeat_runtime_info()
    if not runtime.heartbeat_supported:
        return f"runtime_incompatible: {runtime.warnings[0] if runtime.warnings else _build_runtime_warning(runtime.model)}"
    return None


async def _record_completion_outcome(
    out: HeartbeatResult,
    heartbeat_session_id: str,
    model_review_due: bool,
) -> None:
    """Record success or error in Redis after completion finishes."""
    if out.status == "error":
        await record_heartbeat_error(out.error or "unknown heartbeat error", session_id=heartbeat_session_id)
    else:
        await record_heartbeat_success(
            session_id=heartbeat_session_id,
            did_model_review=model_review_due,
        )


async def _run_persona_heartbeat(input: HeartbeatInput, ctx: Context) -> dict[str, Any]:
    """Periodic persona check-in via complete_internal."""
    manual = input.manual
    target_project_id = input.target_project_id

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

    heartbeat_session_id = str(uuid4())
    await record_heartbeat_attempt(session_id=heartbeat_session_id)
    await set_heartbeat_running(session_id=heartbeat_session_id)
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
        await clear_heartbeat_running()


@hatchet.task(
    name="persona-heartbeat",
    input_validator=HeartbeatInput,
    on_crons=["*/5 * * * *"],
    execution_timeout="7200s",
    concurrency=ConcurrencyExpression(
        expression="'persona_heartbeat'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_NEWEST,
    ),
)
async def persona_heartbeat_task(input: HeartbeatInput, ctx: Context) -> dict[str, Any]:
    return await _run_persona_heartbeat(input, ctx)
