"""Bounded model-based completion review for supervisor sign-off."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.api.complete.core import complete_internal
from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent
from app.services.persona_prompt_service import render_completion_review_prompt

logger = logging.getLogger(__name__)

_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["complete", "continue", "escalate"],
        },
        "reason": {"type": "string"},
        "focus": {"type": "string"},
    },
    "required": ["decision", "reason", "focus"],
}


@dataclass
class CompletionReviewOutcome:
    decision: str | None
    reason: str | None
    focus: str | None
    session_id: str | None
    reviewer_agent_slug: str
    reviewer_model_id: str | None
    used: bool
    raw_content: str | None = None


async def _build_review_prompt(
    *,
    completion_content: str,
    cleanup_status: str,
    workstream_inventory: str,
) -> str:
    return await render_completion_review_prompt(
        completion_content=completion_content,
        cleanup_status=cleanup_status,
        workstream_inventory=workstream_inventory,
    )


def _parse_review_content(content: str | None) -> dict[str, str] | None:
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    decision = parsed.get("decision")
    reason = parsed.get("reason")
    focus = parsed.get("focus")
    if decision not in {"complete", "continue", "escalate"}:
        return None
    if not isinstance(reason, str) or not reason.strip():
        return None
    if not isinstance(focus, str) or not focus.strip():
        return None
    return {
        "decision": decision,
        "reason": reason.strip(),
        "focus": focus.strip(),
    }


async def review_persona_completion(
    *,
    project_id: str,
    completion_content: str,
    cleanup_status: str,
    workstream_inventory: str,
    parent_session_id: str | None = None,
    reviewer_agent_slug: str = "supervisor",
) -> CompletionReviewOutcome:
    """Run one bounded supervisor review over a finished Jenny session."""
    from app.db import async_session

    prompt = await _build_review_prompt(
        completion_content=completion_content,
        cleanup_status=cleanup_status,
        workstream_inventory=workstream_inventory,
    )

    async with async_session() as db:
        try:
            resolved = await resolve_agent(reviewer_agent_slug, db)
            mandate = await inject_agent_mandates(
                resolved.agent,
                db,
                prompt_mode="minimal",
                project_id=project_id,
                task_type="review",
            )
            messages: list[dict[str, Any]] = []
            if mandate.system_content:
                messages.append({"role": "system", "content": mandate.system_content})
            messages.append({"role": "user", "content": prompt})
            result = await complete_internal(
                messages=messages,
                model=resolved.model,
                provider=resolved.provider,
                temperature=resolved.agent.temperature,
                project_id=project_id,
                db=db,
                agent_slug=reviewer_agent_slug,
                request_source="heartbeat_completion_review",
                parent_session_id=parent_session_id,
                use_memory=False,
                enable_caching=False,
                skip_cache=True,
                max_turns=1,
                execute_tools=False,
                thinking_level=resolved.agent.thinking_level,
                response_format={"type": "json_object", "schema": _REVIEW_SCHEMA},
                task_type="review",
                phase="completion_review",
            )
        except Exception:
            logger.warning(
                "Completion review unavailable for reviewer agent '%s'",
                reviewer_agent_slug,
                exc_info=True,
            )
            return CompletionReviewOutcome(
                decision=None,
                reason=None,
                focus=None,
                session_id=None,
                reviewer_agent_slug=reviewer_agent_slug,
                reviewer_model_id=None,
                used=False,
            )

    parsed = _parse_review_content(result.content)
    if parsed is None:
        logger.warning(
            "Completion review returned non-parseable content for reviewer agent '%s': %r",
            reviewer_agent_slug,
            result.content,
        )
        return CompletionReviewOutcome(
            decision=None,
            reason=None,
            focus=None,
            session_id=result.session_id,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=resolved.model,
            used=False,
            raw_content=result.content,
        )

    return CompletionReviewOutcome(
        decision=parsed["decision"],
        reason=parsed["reason"],
        focus=parsed["focus"],
        session_id=result.session_id,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=resolved.model,
        used=True,
        raw_content=result.content,
    )
