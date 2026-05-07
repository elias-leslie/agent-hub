"""Heartbeat prompt builder — thin orchestrator backed by DB prompt content."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime

from app.services.prompt_catalog import PERSONA_HEARTBEAT_PROMPT_SLUG
from app.services.prompt_service import require_prompt_content
from app.workflows._heartbeat_data import (
    _collect_agent_hub_heartbeat_state,
    _collect_summitflow_heartbeat_state,
    _fetch_task_overview,
    _get_active_specialist_inventory,
    _get_active_work_summary,
    _get_agent_roster_summary,
    _get_cleanup_status_summary,
    _get_feedback_summary_section,
    _get_git_status_summary,
    _get_persona_tool_summary,
    _get_protection_status_summary,
    _get_workstream_inventory,
    get_project_access_summary,
)
from app.workflows._heartbeat_failed_tasks import _get_recent_failed_tasks_summary
from app.workflows._heartbeat_recall import (
    HeartbeatRecallSections,
    build_heartbeat_recall_sections,
)

logger = logging.getLogger(__name__)


def _append_unique_sections(prompt: str, *sections: str) -> str:
    seen: set[str] = set()
    for section in sections:
        normalized = " ".join(section.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        prompt += section
    return prompt

_DEFAULT_TIMEZONE = "America/New_York"
_IANA_TZ_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:/[A-Z][a-z_]+)+)\b")
_LEGACY_FETCH_SEAMS = (_fetch_task_overview,)


def _validate_iana_timezone(tz_value: str) -> bool:
    """Return True if tz_value is a valid IANA timezone identifier."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(tz_value)
        return True
    except (ZoneInfoNotFoundError, KeyError):
        return False


async def _get_persona_timezone() -> str:
    """Resolve the persona's timezone from config, user context, or default.

    Priority:
      1. persona.limits["timezone"] (explicit config)
      2. Timezone mentioned in persona.user_context (best-effort regex)
      3. Fall back to America/New_York
    """
    from app.db import async_session
    from app.services._persona_crud import get_persona
    from app.services.persona_document_prompt_service import (
        get_persona_user_context_document,
    )

    try:
        async with async_session() as db:
            persona = await get_persona(db)
            if not persona:
                return _DEFAULT_TIMEZONE
            user_profile = (
                dict(persona.user_profile)
                if isinstance(persona.user_profile, dict)
                else {}
            )
            limits = dict(persona.limits) if isinstance(persona.limits, dict) else {}
            user_context = await get_persona_user_context_document(db)
    except Exception:
        logger.debug("Could not fetch persona for timezone; using default")
        return _DEFAULT_TIMEZONE

    from app.services.persona_documents import get_user_profile_timezone

    profile_timezone = get_user_profile_timezone(user_profile)
    if profile_timezone and _validate_iana_timezone(profile_timezone):
        return profile_timezone

    if limits:
        tz_value = limits.get("timezone")
        if tz_value and isinstance(tz_value, str):
            if _validate_iana_timezone(tz_value):
                return tz_value
            logger.warning("Invalid timezone in persona.limits: %s", tz_value)

    if user_context:
        match = _IANA_TZ_PATTERN.search(user_context)
        if match and _validate_iana_timezone(match.group(1)):
            return match.group(1)

    return _DEFAULT_TIMEZONE


async def _build_core_prompt(
    model_review_due: bool,
    model_review_label: str,
    target_project_id: str | None,
    provider: str | None = None,
) -> str:
    """Render the template-based core prompt and append the execution target if set."""
    from zoneinfo import ZoneInfo

    project_access = await get_project_access_summary()
    now_utc = datetime.now(UTC)
    tz_name = await _get_persona_timezone()
    local_time = now_utc.astimezone(ZoneInfo(tz_name)).strftime("%H:%M %Z")

    review_status = "DUE" if model_review_due else f"not due — {model_review_label}"
    tool_count, persona_tool_list = _get_persona_tool_summary(provider)
    template = await require_prompt_content(PERSONA_HEARTBEAT_PROMPT_SLUG)

    prompt = template.format(
        timestamp=now_utc.strftime("%Y-%m-%d %H:%M UTC"),
        local_time=local_time,
        project_access_summary=project_access,
        model_review_status=review_status,
        tool_count=tool_count,
        persona_tool_list=persona_tool_list,
    )

    if target_project_id:
        prompt += (
            f"\n\nExecution target for this run: {target_project_id}\n"
            "Only take execution actions for this target project in this run. "
            "Use persona-sandbox only for persona-internal state."
        )
    return prompt


async def _append_dynamic_sections(
    prompt: str,
    target_project_id: str | None = None,
    provider: str | None = None,
) -> str:
    """Append optional dynamic data sections to heartbeat prompt."""
    heartbeat_state, agent_hub_state = await asyncio.gather(
        _collect_summitflow_heartbeat_state(target_project_id),
        _collect_agent_hub_heartbeat_state(target_project_id),
    )
    recall_sections_task: asyncio.Task[HeartbeatRecallSections] = asyncio.create_task(
        build_heartbeat_recall_sections(target_project_id)
    )
    task_overview_payload = heartbeat_state.task_overview_payload
    task_overview = None if task_overview_payload is not None else heartbeat_state.task_overview_raw
    (
        active_work,
        protection_status,
        cleanup_status,
        active_specialists,
        agent_roster,
        workstream_inventory,
        recent_failed_tasks,
        git_status,
        feedback_summary,
    ) = await asyncio.gather(
        _get_active_work_summary(
            task_overview=task_overview,
            task_overview_payload=task_overview_payload,
            target_project_id=target_project_id,
            heartbeat_state=heartbeat_state,
            agent_hub_state=agent_hub_state,
        ),
        _get_protection_status_summary(target_project_id),
        _get_cleanup_status_summary(
            target_project_id,
            cleanup_status_response=heartbeat_state.cleanup_status_response,
            workstream_rows=agent_hub_state.workstream_rows,
        ),
        _get_active_specialist_inventory(
            target_project_id,
            agent_hub_state=agent_hub_state,
        ),
        _get_agent_roster_summary(),
        _get_workstream_inventory(
            provider,
            task_overview=task_overview,
            task_overview_payload=task_overview_payload,
            target_project_id=target_project_id,
            heartbeat_state=heartbeat_state,
            agent_hub_state=agent_hub_state,
        ),
        _get_recent_failed_tasks_summary(
            target_project_id,
            heartbeat_state=heartbeat_state,
        ),
        _get_git_status_summary(
            target_project_id,
            git_status_rows=heartbeat_state.git_status_rows,
        ),
        _get_feedback_summary_section(),
    )
    recall_sections = await recall_sections_task
    return _append_unique_sections(
        prompt,
        active_work,
        protection_status,
        cleanup_status,
        active_specialists,
        agent_roster,
        workstream_inventory,
        recent_failed_tasks,
        git_status,
        feedback_summary,
        recall_sections.improvement_signal_digest,
        recall_sections.recent_heartbeat_digest,
        recall_sections.recent_idle_history,
    )


async def build_heartbeat_prompt(
    model_review_due: bool,
    model_review_label: str,
    target_project_id: str | None = None,
    provider: str | None = None,
) -> str:
    """Build heartbeat task prompt with dynamic model review and task state."""
    prompt = await _build_core_prompt(
        model_review_due,
        model_review_label,
        target_project_id,
        provider,
    )
    return await _append_dynamic_sections(prompt, target_project_id, provider)


__all__ = [
    "build_heartbeat_prompt",
]
