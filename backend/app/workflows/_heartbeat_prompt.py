"""Heartbeat prompt template and builder helpers."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

HEARTBEAT_PROMPT_TEMPLATE = """\
Run your regular heartbeat check. Current time: {timestamp} ({local_time})

{project_access_summary}

## Model Review ({model_review_status})
{model_review_instructions}

## Journal Diversity (REQUIRED)
Write at least ONE journal entry this heartbeat. Your recent journal types: {recent_journal_types}.
Rotate types across heartbeats — use a type you haven't used recently:
- observation, decision, learning, user_insight, evolution

## Memory Curation
Review injected memories in your context. Use `mark_memory_relevant` for memories \
useful to your ongoing operations. Use `mark_memory_irrelevant` for noise/outdated ones.

## Available Tools ({tool_count} total)
Beyond bash/read_file/write_file, you have: {persona_tool_list}

Follow your <heartbeat_instructions> from your system context.

Your FINAL message must start with either `HEARTBEAT_OK` or `HEARTBEAT_ACTION`, \
followed by a 1-2 sentence summary. Also include a `[[S:completed:summary here]]` \
or `[[S:partial:summary here]]` tag so the session gets a searchable summary.

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


async def _get_recent_journal_types(limit: int = 5) -> str:
    """Return comma-separated list of recent journal entry types."""
    try:
        from datetime import timedelta

        from app.services.memory.repository import get_memory_repository

        repo = get_memory_repository()
        since = datetime.now(UTC) - timedelta(days=7)
        memories = await repo.list_by_scope_and_tier(
            scope="agent:persona",
            memory_type="journal",
            status="active",
            since=since,
            order_by="created_at",
            limit=limit,
        )
        types = [(m.metadata_ or {}).get("entry_type", "observation") for m in memories]
        return ", ".join(types) if types else "(none yet)"
    except Exception:
        logger.exception("Failed to fetch recent journal types")
        return "(unavailable)"


def _get_persona_tool_summary() -> tuple[int, str]:
    """Return (count, comma-separated list) of persona-specific tool names."""
    try:
        from app.services.tools._persona_tools import PERSONA_EXTRA_TOOLS

        names = [t.name for t in PERSONA_EXTRA_TOOLS]
        return len(names), ", ".join(names)
    except Exception:
        logger.exception("Failed to list persona tools")
        return 0, "(unavailable)"


async def _get_active_work_summary() -> str:
    """Build an <active_work> XML block with running tasks and live sessions.

    Uses st CLI for tasks (matches manage_tasks pattern) and
    query_active_sessions() for live Agent Hub sessions.
    """
    sections: list[str] = []

    # -- Running/queued tasks via st CLI --
    try:
        proc = subprocess.run(
            ["st", "list", "--status", "running,queue", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        tasks = json.loads(proc.stdout) if proc.stdout.strip() else []
        if tasks:
            lines = [f"Running/queued tasks: {len(tasks)}"]
            for t in tasks[:10]:
                tid = t.get("id", "?")
                title = t.get("title", "untitled")
                status = t.get("status", "?")
                phase = t.get("phase", "?")
                proj = t.get("project_id", "")
                proj_suffix = f" ({proj})" if proj else ""
                lines.append(f"- [{status}/{phase}] {tid}: {title}{proj_suffix}")
            sections.append("\n".join(lines))
    except Exception:
        logger.debug("Failed to fetch active tasks for heartbeat prompt", exc_info=True)

    # -- Active Agent Hub sessions --
    try:
        from app.db import async_session
        from app.services.memory.continuity_query import query_active_sessions

        async with async_session() as db:
            sessions = await query_active_sessions(db, max_entries=5)

        if sessions:
            lines = [f"Active agent sessions: {len(sessions)}"]
            for s in sessions:
                agent = s.get("agent_slug", "session")
                project = s.get("project_id", "unknown")
                parts: list[str] = []
                if s.get("external_id"):
                    parts.append(s["external_id"])
                if s.get("current_branch"):
                    parts.append(f"branch: {s['current_branch']}")
                fc = s.get("touched_file_count", 0)
                if fc:
                    parts.append(f"files: {fc}")
                detail = ", ".join(parts) if parts else f"{s.get('event_count', 0)} events"
                lines.append(f"- {agent} on {project}, {detail}")
            sections.append("\n".join(lines))
    except Exception:
        logger.debug("Failed to fetch active sessions for heartbeat prompt", exc_info=True)

    if not sections:
        return ""

    body = "\n\n".join(sections)
    return f"\n<active_work>\n{body}\n</active_work>"


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
