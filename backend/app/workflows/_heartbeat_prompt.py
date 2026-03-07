"""Heartbeat prompt builder — thin orchestrator.

Constants and data helpers live in sibling modules:
  _heartbeat_templates  — string constants
  _heartbeat_data       — async/sync data-fetching helpers
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from app.workflows._heartbeat_data import (
    _get_active_work_summary,
    _get_agent_roster_summary,
    _get_feedback_summary_section,
    _get_git_status_summary,
    _get_persona_tool_summary,
    _get_workstream_inventory,
    get_project_access_summary,
)
from app.workflows._heartbeat_templates import (
    HEARTBEAT_PROMPT_TEMPLATE,
    MODEL_REVIEW_DO,
    MODEL_REVIEW_SKIP,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEZONE = "America/New_York"


async def _get_persona_timezone() -> str:
    """Resolve the persona's timezone from config, user context, or default.

    Priority:
      1. persona.limits["timezone"] (explicit config)
      2. Timezone mentioned in persona.user_context (best-effort regex)
      3. Fall back to America/New_York
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
            try:
                ZoneInfo(tz_value)
                return tz_value
            except (ZoneInfoNotFoundError, KeyError):
                logger.warning("Invalid timezone in persona.limits: %s", tz_value)

    # 2. Best-effort extraction from user_context
    if persona.user_context:
        # Match common IANA timezone patterns like America/Chicago, Europe/London, etc.
        match = re.search(
            r"\b([A-Z][a-z]+(?:/[A-Z][a-z_]+)+)\b", persona.user_context
        )
        if match:
            candidate = match.group(1)
            try:
                ZoneInfo(candidate)
                return candidate
            except (ZoneInfoNotFoundError, KeyError):
                pass

    return _DEFAULT_TIMEZONE


async def build_heartbeat_prompt(model_review_due: bool, model_review_label: str) -> str:
    """Build the heartbeat prompt with dynamic model review and project access."""
    from zoneinfo import ZoneInfo

    project_access = await get_project_access_summary()
    now_utc = datetime.now(UTC)
    tz_name = await _get_persona_timezone()
    local_tz = ZoneInfo(tz_name)
    local_time = now_utc.astimezone(local_tz).strftime("%H:%M %Z")

    review_status = "DUE" if model_review_due else f"not due — {model_review_label}"
    review_instructions = MODEL_REVIEW_DO if model_review_due else MODEL_REVIEW_SKIP

    tool_count, persona_tool_list = _get_persona_tool_summary()

    prompt = HEARTBEAT_PROMPT_TEMPLATE.format(
        timestamp=now_utc.strftime("%Y-%m-%d %H:%M UTC"),
        local_time=local_time,
        project_access_summary=project_access,
        model_review_status=review_status,
        model_review_instructions=review_instructions,
        tool_count=tool_count,
        persona_tool_list=persona_tool_list,
    )

    active_work = await _get_active_work_summary()
    if active_work:
        prompt += active_work

    agent_roster = await _get_agent_roster_summary()
    if agent_roster:
        prompt += agent_roster

    workstream_inventory = await _get_workstream_inventory()
    if workstream_inventory:
        prompt += workstream_inventory

    git_state = _get_git_status_summary()
    if git_state:
        prompt += git_state

    feedback_summary = await _get_feedback_summary_section()
    if feedback_summary:
        prompt += feedback_summary

    return prompt


__all__ = [
    "HEARTBEAT_PROMPT_TEMPLATE",
    "MODEL_REVIEW_DO",
    "MODEL_REVIEW_SKIP",
    "_get_active_work_summary",
    "_get_agent_roster_summary",
    "_get_feedback_summary_section",
    "_get_git_status_summary",
    "_get_persona_timezone",
    "_get_persona_tool_summary",
    "_get_workstream_inventory",
    "build_heartbeat_prompt",
    "get_project_access_summary",
]
