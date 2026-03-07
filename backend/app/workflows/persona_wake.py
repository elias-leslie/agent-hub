"""Persona wake workflow — event-driven agent invocations.

Dispatched by the /api/wake endpoint when external events (task failures,
quality gate failures, autocode completions) need the persona's attention.
Each wake gets its own ephemeral session for isolation.
"""

from __future__ import annotations

import logging
from typing import Any

from hatchet_sdk import Context
from pydantic import BaseModel

from app.hatchet_app import hatchet
from app.workflows._session_postprocess import ensure_session_summary

logger = logging.getLogger(__name__)


class WakeInput(BaseModel):
    agent_slug: str
    model: str
    provider: str
    temperature: float = 0.7
    prompt: str
    project_id: str = "summitflow"
    event_type: str = "generic"
    thinking_level: str | None = None
    max_turns: int | None = None


class WakeResult(BaseModel):
    status: str
    turns: int = 0
    tool_calls: int = 0
    event_type: str = "generic"
    error: str | None = None
    summary_stored: bool = False


_WAKE_TOOLING_HINTS = """Operational notes:
- Use current `st` syntax when inspecting tasks/sessions: `st ready-all`, `st ready --limit N`, `st sessions list --status <status> --limit N`.
- For observability: use `st session-events <session_id>` for a direct session id, or `st session-events -T task-123 --page-size 100` for a task-linked session trace.
- Do not add stale flags like `-P`, `--project`, `--human`, or `--compact` to `st ready` / `st ready-all`.
- Do not use `--session` with `st session-events`; pass the session id as the positional argument instead.
- Never pass `st sessions list` output `session_id` values to `st session-events`; they are ST session ids, not Agent Hub session ids.
- Only use `st session-events <session_id>` when you already have a real Agent Hub session UUID from Agent Hub context or heartbeat results.
- If `st session-events -T task-...` reports no linked Agent Hub sessions, treat that as evidence and move on; do not probe ST internal worktree paths trying to force more context.
- Stay inside repo-local evidence and `.st/snapshots/*.meta.json`; do not inspect `/home/kasadis/.local/share/st/worktrees/...` or other external ST internals unless the prompt explicitly requires it.
- Use `st context <task-id>` only when you have a real task id.
- Prefer the known-good commands above over probing multiple invalid `st` variants.
- Avoid exploratory `--help` calls unless a known-good command above still fails.
- Prefer investigation over feature work unless the prompt explicitly asks for implementation.
"""


def _build_wake_prompt(prompt: str) -> str:
    """Prefix wake prompts with concise operational hints to reduce CLI thrash."""
    prompt = prompt.strip()
    return f"{_WAKE_TOOLING_HINTS}\nTask:\n{prompt}" if prompt else _WAKE_TOOLING_HINTS.strip()


@hatchet.task(
    name="agent-wake",
    execution_timeout="7200s",
    retries=0,
    input_validator=WakeInput,
)
async def agent_wake_task(input: WakeInput, ctx: Context) -> dict[str, Any]:
    """Run an agent completion in response to an external event."""
    from app.api.complete.core import complete_internal
    from app.db import async_session
    from app.services.project_permission_service import get_project_permission

    # Check project permission — skip if tier is "off"
    async with async_session() as perm_db:
        perm = await get_project_permission(perm_db, input.project_id)
        if perm and perm.permission_tier == "off":
            ctx.log(f"Wake skipped for {input.project_id} (permission_tier=off)")
            return WakeResult(
                status="skipped",
                event_type=input.event_type,
                error="project_permission_off",
            ).model_dump()

    memory_group = f"{input.project_id}:wake:{input.event_type}"

    # Resolve max_turns: explicit > persona limit > 200 fallback
    from app.services._persona_crud import get_persona_limit
    from app.services.persona_service import get_persona

    async with async_session() as db:
        if input.max_turns:
            max_turns = input.max_turns
        else:
            persona = await get_persona(db)
            max_turns = get_persona_limit(persona, "max_turns") or 200

        result = await complete_internal(
            messages=[{"role": "user", "content": _build_wake_prompt(input.prompt)}],
            model=input.model,
            provider=input.provider,
            temperature=input.temperature,
            project_id=input.project_id,
            db=db,
            agent_slug=input.agent_slug,
            use_memory=True,
            memory_group_id=memory_group,
            enable_caching=False,
            skip_cache=True,
            max_turns=max_turns,
            execute_tools=True,
            enable_programmatic_tools=True,
            task_type="wake",
            phase=input.event_type,
            thinking_level=input.thinking_level,
        )

    summary_stored = await ensure_session_summary(
        result.session_id,
        result.content or "",
        agent_id=input.agent_slug,
    )

    out = WakeResult(
        status=result.status or "success",
        turns=result.turns,
        tool_calls=result.tool_calls_count,
        event_type=input.event_type,
        error=result.error,
        summary_stored=summary_stored,
    )
    ctx.log(
        f"Agent wake ({input.agent_slug}/{input.event_type}): "
        f"{out.turns} turns, {out.tool_calls} tool calls, summary_stored={summary_stored}"
    )
    return out.model_dump()


def dispatch_wake(
    agent_slug: str,
    model: str,
    provider: str,
    temperature: float,
    prompt: str,
    project_id: str,
    event_type: str,
    thinking_level: str | None = None,
    max_turns: int | None = None,
) -> None:
    """Dispatch a wake workflow via Hatchet (fire-and-forget)."""
    wake_input = WakeInput(
        agent_slug=agent_slug,
        model=model,
        provider=provider,
        temperature=temperature,
        prompt=prompt,
        project_id=project_id,
        event_type=event_type,
        thinking_level=thinking_level,
        max_turns=max_turns,
    )
    agent_wake_task.run_no_wait(wake_input)
    logger.info("Dispatched wake workflow for %s/%s", agent_slug, event_type)
