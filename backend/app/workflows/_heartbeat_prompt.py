"""Heartbeat prompt builder — thin orchestrator backed by DB prompt content."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from app.services.prompt_catalog import PERSONA_HEARTBEAT_PROMPT_SLUG
from app.services.prompt_service import require_prompt_content
from app.workflows._heartbeat_data import (
    _get_active_specialist_inventory,
    _get_active_work_summary,
    _get_agent_roster_summary,
    _get_cleanup_status_summary,
    _get_feedback_summary_section,
    _get_git_status_summary,
    _get_persona_tool_summary,
    _get_workstream_inventory,
    get_project_access_summary,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEZONE = "America/New_York"
MODEL_REVIEW_DO = (
    "Due — run `review_agent_performance` + `manage_model_config(action=get_benchmarks)` + "
    "`manage_model_config(action=list_agents)`. Check `synced_at` — if benchmark data >60 days old, "
    "`send_push` to flag stale benchmarks. Evaluate model assignments. Log via `log_agent_performance`."
)
MODEL_REVIEW_SKIP = "Not due — skip model review this heartbeat."
_IANA_TZ_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:/[A-Z][a-z_]+)+)\b")


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

    try:
        async with async_session() as db:
            persona = await get_persona(db)
    except Exception:
        logger.debug("Could not fetch persona for timezone; using default")
        return _DEFAULT_TIMEZONE

    if not persona:
        return _DEFAULT_TIMEZONE

    # 1. Check explicit timezone in limits
    if persona.limits and isinstance(persona.limits, dict):
        tz_value = persona.limits.get("timezone")
        if tz_value and isinstance(tz_value, str):
            if _validate_iana_timezone(tz_value):
                return tz_value
            logger.warning("Invalid timezone in persona.limits: %s", tz_value)

    # 2. Best-effort extraction from user_context (IANA format e.g. America/Chicago)
    if persona.user_context:
        match = _IANA_TZ_PATTERN.search(persona.user_context)
        if match and _validate_iana_timezone(match.group(1)):
            return match.group(1)

    return _DEFAULT_TIMEZONE


async def _build_core_prompt(
    model_review_due: bool,
    model_review_label: str,
    target_project_id: str | None,
) -> str:
    """Render the template-based core prompt and append the execution target if set."""
    from zoneinfo import ZoneInfo

    project_access = await get_project_access_summary()
    now_utc = datetime.now(UTC)
    tz_name = await _get_persona_timezone()
    local_time = now_utc.astimezone(ZoneInfo(tz_name)).strftime("%H:%M %Z")

    review_status = "DUE" if model_review_due else f"not due — {model_review_label}"
    review_instructions = MODEL_REVIEW_DO if model_review_due else MODEL_REVIEW_SKIP
    tool_count, persona_tool_list = _get_persona_tool_summary()
    template = await require_prompt_content(PERSONA_HEARTBEAT_PROMPT_SLUG)

    prompt = template.format(
        timestamp=now_utc.strftime("%Y-%m-%d %H:%M UTC"),
        local_time=local_time,
        project_access_summary=project_access,
        model_review_status=review_status,
        model_review_instructions=review_instructions,
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


async def _append_dynamic_sections(prompt: str) -> str:
    """Append optional dynamic data sections to the heartbeat prompt."""
    for section in (
        await _get_active_work_summary(),
        _get_cleanup_status_summary(),
        await _get_active_specialist_inventory(),
        await _get_agent_roster_summary(),
        await _get_workstream_inventory(),
        _get_git_status_summary(),
        await _get_feedback_summary_section(),
    ):
        if section:
            prompt += section
    return prompt


async def build_heartbeat_prompt(
    model_review_due: bool,
    model_review_label: str,
    target_project_id: str | None = None,
) -> str:
    """Build the heartbeat prompt with dynamic model review and project access."""
    prompt = await _build_core_prompt(model_review_due, model_review_label, target_project_id)
    return await _append_dynamic_sections(prompt)


__all__ = [
    "MODEL_REVIEW_DO",
    "MODEL_REVIEW_SKIP",
    "build_heartbeat_prompt",
]
