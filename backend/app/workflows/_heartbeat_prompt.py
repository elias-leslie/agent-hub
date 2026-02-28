"""Heartbeat prompt template and builder helpers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

HEARTBEAT_PROMPT_TEMPLATE = """\
Run your regular heartbeat check. Current time: {timestamp} ({local_time})

{project_access_summary}

## Model Review ({model_review_status})
{model_review_instructions}

Follow your <heartbeat_instructions> from your system context.

Your FINAL message must start with either `HEARTBEAT_OK` or `HEARTBEAT_ACTION`, \
followed by a 1-2 sentence summary.

If approaching your turn limit, prioritize journaling findings before doing more work.\
"""

MODEL_REVIEW_DO = (
    "Due — run `review_agent_performance` + `manage_model_config(action=get_benchmarks)` + "
    "`manage_model_config(action=list_agents)`. Check `synced_at` — if benchmark data >60 days old, "
    "`send_push` to flag stale benchmarks. Evaluate model assignments. Log via `log_agent_performance`."
)
MODEL_REVIEW_SKIP = "Not due — skip model review this heartbeat."


async def get_project_access_summary() -> str:
    """Build a summary of project access tiers for the heartbeat prompt."""
    from sqlalchemy import text

    from app.db import async_session

    try:
        async with async_session() as db:
            result = await db.execute(
                text(
                    "SELECT project_id, permission_tier, auto_exec_enabled"
                    " FROM project_permissions ORDER BY project_id"
                )
            )
            rows = result.fetchall()

        if not rows:
            return "Your project access: (no projects configured)"

        lines = ["Your project access:"]
        for row in rows:
            auto = "auto-exec" if row.auto_exec_enabled else "manual"
            lines.append(f"- {row.project_id}: {row.permission_tier} ({auto})")
        return "\n".join(lines)
    except Exception:
        logger.exception("Failed to fetch project access summary")
        return "Your project access: (unavailable)"


async def build_heartbeat_prompt(model_review_due: bool, model_review_label: str) -> str:
    """Build the heartbeat prompt with dynamic model review and project access."""
    from zoneinfo import ZoneInfo

    project_access = await get_project_access_summary()
    now_utc = datetime.now(UTC)
    local_tz = ZoneInfo("America/New_York")
    local_time = now_utc.astimezone(local_tz).strftime("%H:%M %Z")

    review_status = "DUE" if model_review_due else f"not due — {model_review_label}"
    review_instructions = MODEL_REVIEW_DO if model_review_due else MODEL_REVIEW_SKIP

    return HEARTBEAT_PROMPT_TEMPLATE.format(
        timestamp=now_utc.strftime("%Y-%m-%d %H:%M UTC"),
        local_time=local_time,
        project_access_summary=project_access,
        model_review_status=review_status,
        model_review_instructions=review_instructions,
    )


__all__ = [
    "HEARTBEAT_PROMPT_TEMPLATE",
    "MODEL_REVIEW_DO",
    "MODEL_REVIEW_SKIP",
    "build_heartbeat_prompt",
    "get_project_access_summary",
]
