"""Prompt construction for memory review batches."""

from __future__ import annotations

import json
from typing import Any

from app.models.memory_unified import Memory

from .repository import TIER_REVERSE

MAX_REVIEW_CONTENT_CHARS = 520
MAX_REVIEW_GOVERNANCE_CHARS = 2400

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "uuid": {"type": "string"},
                    "decision": {
                        "type": "string",
                        "enum": ["keep", "retarget", "compress", "archive", "merge", "split"],
                    },
                    "review_status": {
                        "type": "string",
                        "enum": ["clean", "needs_action"],
                    },
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                    "suggested_summary": {"type": ["string", "null"]},
                    "compact_content": {"type": ["string", "null"]},
                    "suggested_tags": {"type": "array", "items": {"type": "string"}},
                    "suggested_applicability": {"type": "object"},
                    "sensitivity_tier": {
                        "type": "string",
                        "enum": ["normal", "personal", "confidential"],
                    },
                },
                "required": [
                    "uuid",
                    "decision",
                    "review_status",
                    "confidence",
                    "reason",
                    "suggested_summary",
                    "suggested_tags",
                    "suggested_applicability",
                    "sensitivity_tier",
                ],
            },
        }
    },
    "required": ["reviews"],
}


def _memory_payload(memory: Memory) -> dict[str, Any]:
    content = " ".join((memory.content or "").split())
    payload: dict[str, Any] = {
        "uuid": str(memory.id),
        "uuid8": memory.uuid_short,
        "name": memory.name,
        "summary": memory.summary,
        "content": content[:MAX_REVIEW_CONTENT_CHARS],
        "content_chars": len(content),
        "memory_type": memory.memory_type,
        "tier": TIER_REVERSE.get(int(memory.tier or 0), "reference"),
        "context_kind": memory.context_kind,
        "scope": memory.scope,
        "scope_id": memory.scope_id,
        "group_id": memory.group_id,
        "tags": list(memory.tags or []),
        "applicability": dict(memory.applicability or {}),
        "trigger_task_types": list(memory.trigger_task_types or []),
        "trigger_phases": list(memory.trigger_phases or []),
        "usage": {
            "loaded": int(memory.loaded_count or 0),
            "referenced": int(memory.referenced_count or 0),
            "helpful": int(memory.helpful_count or 0),
            "harmful": int(memory.harmful_count or 0),
        },
        "token_count": memory.token_count,
        "review_status": memory.review_status,
        "compact_content": (memory.metadata_ or {}).get("compact_content"),
        "compact_status": (memory.metadata_ or {}).get("compact_status"),
        "compact_reviewed_at": (memory.metadata_ or {}).get("compact_reviewed_at"),
        "last_reviewed_at": memory.last_reviewed_at.isoformat()
        if memory.last_reviewed_at
        else None,
    }
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [], {})
    }


def build_memory_review_prompt(
    memories: list[Memory],
    *,
    governance_snapshot: dict[str, Any],
) -> str:
    """Build bounded prompt for the memory-curator agent."""
    payload = [_memory_payload(memory) for memory in memories]
    governance_json = json.dumps(
        governance_snapshot,
        separators=(",", ":"),
        sort_keys=True,
    )[:MAX_REVIEW_GOVERNANCE_CHARS]
    memories_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return (
        "Review these Agent Hub memories for quality, token efficiency, staleness, "
        "assignment, scope, and routing.\n\n"
        "Use compact evidence only. Return review decisions only. "
        "Prefer compact summaries and targeted applicability. Mark needs_action when content is "
        "stale, too broad, too long for its tier, assigned to wrong consumers, "
        "duplicative, or risky.\n\n"
        "For any useful memory over ~60 tokens, provide compact_content: the prompt-ready "
        "version to inject instead of full content. Preserve all hard directives and normative "
        "force (must, never, always, required, only, do not). Compact first; do not rely on "
        "dropping useful memories to save tokens.\n\n"
        "Consumer profiles: agent_startup, agent_coding, "
        "agent_operator, agent_promptops, agent_general, agent_visual, agent_runtime.\n"
        "Policy memories should not be agent-targeted unless there is a strong reason. "
        "References and capabilities should be targeted when broad injection would bloat context.\n\n"
        f"Governance snapshot:\n{governance_json}\n\n"
        f"Memories:\n{memories_json}\n\n"
        "Return JSON only matching the provided schema."
    )


__all__ = [
    "REVIEW_SCHEMA",
    "build_memory_review_prompt",
]
