"""Heartbeat prompt builder — thin orchestrator.

Constants and data helpers live in sibling modules:
  _heartbeat_templates  — string constants
  _heartbeat_data       — async/sync data-fetching helpers
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.workflows._heartbeat_data import (
    _get_active_work_summary,
    _get_persona_tool_summary,
    _get_recent_journal_types,
    get_project_access_summary,
)
from app.workflows._heartbeat_templates import (
    HEARTBEAT_PROMPT_TEMPLATE,
    MODEL_REVIEW_DO,
    MODEL_REVIEW_SKIP,
)


async def build_heartbeat_prompt(model_review_due: bool, model_review_label: str) -> str:
    """Build the heartbeat prompt with dynamic model review and project access."""
    from zoneinfo import ZoneInfo

    project_access = await get_project_access_summary()
    now_utc = datetime.now(UTC)
    local_tz = ZoneInfo("America/New_York")
    local_time = now_utc.astimezone(local_tz).strftime("%H:%M %Z")

    review_status = "DUE" if model_review_due else f"not due — {model_review_label}"
    review_instructions = MODEL_REVIEW_DO if model_review_due else MODEL_REVIEW_SKIP

    recent_journal_types = await _get_recent_journal_types()
    tool_count, persona_tool_list = _get_persona_tool_summary()

    prompt = HEARTBEAT_PROMPT_TEMPLATE.format(
        timestamp=now_utc.strftime("%Y-%m-%d %H:%M UTC"),
        local_time=local_time,
        project_access_summary=project_access,
        model_review_status=review_status,
        model_review_instructions=review_instructions,
        recent_journal_types=recent_journal_types,
        tool_count=tool_count,
        persona_tool_list=persona_tool_list,
    )

    active_work = await _get_active_work_summary()
    if active_work:
        prompt += active_work

    return prompt


__all__ = [
    "HEARTBEAT_PROMPT_TEMPLATE",
    "MODEL_REVIEW_DO",
    "MODEL_REVIEW_SKIP",
    "_get_active_work_summary",
    "_get_persona_tool_summary",
    "_get_recent_journal_types",
    "build_heartbeat_prompt",
    "get_project_access_summary",
]
