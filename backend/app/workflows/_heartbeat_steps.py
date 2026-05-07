"""Implementation helpers for persona_heartbeat — extracted to keep main module concise."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from app.core.project_roots import resolve_project_root
from app.workflows._heartbeat_prompt import build_heartbeat_prompt
from app.workflows._heartbeat_redis import (
    check_redis_elapsed,
    get_model_review_status,
    record_heartbeat_error,
    record_heartbeat_success,
)

logger = logging.getLogger(__name__)

HEARTBEAT_PROJECT = "persona-sandbox"
HEARTBEAT_MEMORY_GROUP = "project:persona-sandbox"
_DEFAULT_INTERVAL_MINUTES = 60


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


def _build_runtime_warning(model: str) -> str:
    return f"Heartbeat requires tool execution, but {model} does not support tools."


async def _resolve_persona(
    db: Any,
    project_id: str = HEARTBEAT_PROJECT,
) -> tuple[str, str, float, str | None, str, dict[str, Any] | None]:
    """Return (model, provider, temperature, thinking_level, system_content, memory_config)."""
    from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

    resolved = await resolve_agent("persona", db)
    agent = resolved.agent
    provider = resolved.provider
    mandate = await inject_agent_mandates(
        agent, db, prompt_mode="full", project_id=project_id, task_type="heartbeat"
    )
    return (
        resolved.model,
        provider,
        agent.temperature,
        agent.thinking_level,
        mandate.system_content,
        agent.memory_config,
    )


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


def _get_skip_reason(
    interval_minutes: int, onboarding_complete: bool, execution_state: str = "active"
) -> str:
    """Return a human-readable reason the heartbeat was skipped."""
    if execution_state == "paused":
        return "paused"
    if interval_minutes == 0:
        return "disabled"
    return "not onboarded" if not onboarding_complete else "interval not elapsed"


async def _should_run() -> tuple[bool, int, bool, str]:
    """Return (should_run, interval_minutes, onboarding_complete, execution_state)."""
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


async def _resolve_completion_context(
    execution_project: str,
) -> tuple[str, str, float, str | None, str, dict[str, Any] | None, int]:
    """Resolve persona agent config and max_turns for a heartbeat completion."""
    from app.db import async_session
    from app.services._persona_crud import get_persona_limit
    from app.services.persona_service import get_persona

    async with async_session() as db:
        model, provider, temperature, thinking_level, system_content, agent_memory_config = (
            await _resolve_persona(db, project_id=execution_project)
        )
        persona = await get_persona(db)
        max_turns = get_persona_limit(persona, "max_turns")
    return model, provider, temperature, thinking_level, system_content, agent_memory_config, max_turns


async def _invoke_complete_internal(
    db: Any,
    *,
    messages: list[dict[str, Any]],
    model: str,
    provider: str,
    temperature: float,
    execution_project: str,
    heartbeat_session_id: str,
    memory_config: dict[str, Any] | None,
    max_turns: int,
    thinking_level: str | None,
    working_dir: str | None,
) -> Any:
    """Call complete_internal with heartbeat-standard parameters."""
    from app.api.complete.core import complete_internal

    return await complete_internal(
        messages=messages,
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
        memory_config=memory_config,
        enable_caching=False,
        skip_cache=True,
        max_turns=max_turns,
        execute_tools=True,
        enable_programmatic_tools=True,
        defer_tool_loading=True,
        task_type="heartbeat",
        thinking_level=thinking_level,
        working_dir=working_dir,
        requested_model=model,
        requested_provider=provider,
    )


async def _do_completion(
    interval_minutes: int,
    *,
    heartbeat_session_id: str,
    target_project_id: str | None = None,
):
    """Run the actual completion call — separated for error handling."""
    from app.db import async_session

    model_review_due, model_review_label = await get_model_review_status()
    execution_project = target_project_id or HEARTBEAT_PROJECT

    model, provider, temperature, thinking_level, system_content, agent_memory_config, max_turns = (
        await _resolve_completion_context(execution_project)
    )
    heartbeat_prompt = await build_heartbeat_prompt(
        model_review_due, model_review_label, target_project_id=target_project_id, provider=provider,
    )
    execution_root = resolve_project_root(execution_project)
    async with async_session() as db:
        result = await _invoke_complete_internal(
            db,
            messages=_build_messages(system_content, heartbeat_prompt),
            model=model,
            provider=provider,
            temperature=temperature,
            execution_project=execution_project,
            heartbeat_session_id=heartbeat_session_id,
            memory_config=agent_memory_config,
            max_turns=max_turns,
            thinking_level=thinking_level,
            working_dir=str(execution_root) if execution_root else None,
        )

    return result, model_review_due


async def _check_schedule_guards(manual: bool) -> tuple[bool, int, str | None]:
    """Check schedule/onboarding guards; returns (may_proceed, interval_minutes, skip_reason)."""
    if not manual:
        should_run, interval_minutes, onboarding_complete, execution_state = await _should_run()
        if not should_run:
            return (
                False,
                interval_minutes,
                _get_skip_reason(interval_minutes, onboarding_complete, execution_state),
            )
        return True, interval_minutes, None

    interval_minutes, onboarding_complete = await get_heartbeat_interval()
    execution_state = await get_persona_execution_state()
    if not onboarding_complete:
        return False, interval_minutes, "not onboarded"
    if execution_state == "paused":
        return False, interval_minutes, "paused"
    return True, interval_minutes, None


async def _check_runtime_guards(target_project_id: str | None) -> str | None:
    """Return a skip reason if permissions or runtime prevent execution, else None."""
    if not await check_project_permission(target_project_id or HEARTBEAT_PROJECT):
        return "project_permission_off"
    runtime = await get_heartbeat_runtime_info()
    if not runtime.heartbeat_supported:
        return (
            f"runtime_incompatible: "
            f"{runtime.warnings[0] if runtime.warnings else _build_runtime_warning(runtime.model)}"
        )
    return None


async def _record_completion_outcome(
    out: Any,
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
