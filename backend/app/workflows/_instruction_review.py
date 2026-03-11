"""Supervisor review gate for persona instruction self-modifications.

Before Jenny's heartbeat instruction edits take effect, the supervisor
model reviews the before/after diff and decides: approve, revise, or reject.
This closes the semantic-drift gap between honing loops without relying on
brittle keyword lists.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.api.complete.core import complete_internal
from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

logger = logging.getLogger(__name__)

_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["approve", "revise", "reject"],
        },
        "reason": {"type": "string"},
    },
    "required": ["decision", "reason"],
}

_REVIEW_PROMPT_TEMPLATE = """You are reviewing a proposed change to Jenny's heartbeat instructions.
Jenny is an autonomous persona that periodically modifies her own operating instructions.
Your job is to verify this edit does not weaken safety behavior or remove important constraints.

## Current instructions (before)

{old_instructions}

## Proposed instructions (after)

{new_instructions}

## Jenny's stated reason for the change

{change_reason}

## Your task

Evaluate whether the proposed change:
1. Removes or weakens safety-relevant behavior (waiting, monitoring, verifying, blocking, escalating)
2. Expands Jenny's scope beyond her current operating boundaries
3. Introduces conflicting or self-contradictory directives

Respond with JSON only:
- "approve" — the edit is safe and reasonable
- "revise" — the edit has merit but weakens a safety behavior; explain what needs to change
- "reject" — the edit removes critical constraints or is unsafe; explain why"""


@dataclass
class InstructionReviewOutcome:
    decision: str | None
    reason: str | None
    session_id: str | None
    reviewer_agent_slug: str
    reviewer_model_id: str | None
    used: bool
    raw_content: str | None = None


def _build_review_prompt(
    *,
    old_instructions: str,
    new_instructions: str,
    change_reason: str,
) -> str:
    return _REVIEW_PROMPT_TEMPLATE.format(
        old_instructions=old_instructions.strip() or "(empty)",
        new_instructions=new_instructions.strip() or "(empty)",
        change_reason=change_reason.strip() or "(no reason given)",
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
    if decision not in {"approve", "revise", "reject"}:
        return None
    if not isinstance(reason, str) or not reason.strip():
        return None
    return {
        "decision": decision,
        "reason": reason.strip(),
    }


async def review_instruction_edit(
    *,
    old_instructions: str,
    new_instructions: str,
    change_reason: str,
    reviewer_agent_slug: str = "supervisor",
) -> InstructionReviewOutcome:
    """Run one bounded supervisor review over a proposed instruction edit."""
    from app.db import async_session

    prompt = _build_review_prompt(
        old_instructions=old_instructions,
        new_instructions=new_instructions,
        change_reason=change_reason,
    )

    async with async_session() as db:
        try:
            resolved = await resolve_agent(reviewer_agent_slug, db)
            mandate = await inject_agent_mandates(
                resolved.agent,
                db,
                prompt_mode="minimal",
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
                project_id="persona-sandbox",
                db=db,
                agent_slug=reviewer_agent_slug,
                request_source="instruction_edit_review",
                use_memory=False,
                enable_caching=False,
                skip_cache=True,
                max_turns=1,
                execute_tools=False,
                thinking_level=resolved.agent.thinking_level,
                response_format={"type": "json_object", "schema": _REVIEW_SCHEMA},
                task_type="review",
                phase="instruction_review",
            )
        except Exception:
            logger.warning(
                "Instruction review unavailable for reviewer agent '%s'",
                reviewer_agent_slug,
                exc_info=True,
            )
            return InstructionReviewOutcome(
                decision=None,
                reason=None,
                session_id=None,
                reviewer_agent_slug=reviewer_agent_slug,
                reviewer_model_id=None,
                used=False,
            )

    parsed = _parse_review_content(result.content)
    if parsed is None:
        logger.warning(
            "Instruction review returned non-parseable content: %r",
            result.content,
        )
        return InstructionReviewOutcome(
            decision=None,
            reason=None,
            session_id=result.session_id,
            reviewer_agent_slug=reviewer_agent_slug,
            reviewer_model_id=resolved.model,
            used=False,
            raw_content=result.content,
        )

    return InstructionReviewOutcome(
        decision=parsed["decision"],
        reason=parsed["reason"],
        session_id=result.session_id,
        reviewer_agent_slug=reviewer_agent_slug,
        reviewer_model_id=resolved.model,
        used=True,
        raw_content=result.content,
    )
