"""Prompt construction for memory review batches."""

from __future__ import annotations

import json
from typing import Any

from app.models.memory_unified import Memory

from .repository import TIER_REVERSE

REVIEW_CHECK_KEYS = (
    "currency",
    "correctness",
    "appropriateness",
    "scope_applicability",
    "conflict",
    "redundancy",
    "lifecycle",
    "authority",
    "token_efficiency",
)

_CHECK_SCHEMA = {
    "type": "string",
    "enum": ["pass", "concern", "unknown", "not_applicable"],
}

_STRING_LIST_SCHEMA = {"type": "array", "items": {"type": "string"}}
_SUGGESTED_APPLICABILITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scope": {"type": "string", "enum": ["global", "project", "agent"]},
        "scope_id": {"type": ["string", "null"]},
        "context_kind": {
            "type": "string",
            "enum": ["policy", "reference", "capability", "continuity"],
        },
        "tier": {
            "type": "string",
            "enum": ["mandate", "guardrail", "reference", "archive"],
        },
        "consumer_profiles": _STRING_LIST_SCHEMA,
        "consumer_surfaces": _STRING_LIST_SCHEMA,
        "agent_slugs": _STRING_LIST_SCHEMA,
        "audience_tags": _STRING_LIST_SCHEMA,
        "exclude_consumer_profiles": _STRING_LIST_SCHEMA,
        "exclude_consumer_surfaces": _STRING_LIST_SCHEMA,
        "exclude_agent_slugs": _STRING_LIST_SCHEMA,
        "exclude_audience_tags": _STRING_LIST_SCHEMA,
        "trigger_task_types": _STRING_LIST_SCHEMA,
        "trigger_phases": _STRING_LIST_SCHEMA,
    },
}

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
                    "merge_target_uuid": {"type": ["string", "null"]},
                    "checks": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {key: _CHECK_SCHEMA for key in REVIEW_CHECK_KEYS},
                        "required": list(REVIEW_CHECK_KEYS),
                    },
                    "suggested_summary": {"type": ["string", "null"]},
                    "compact_content": {"type": ["string", "null"]},
                    "suggested_tags": {"type": "array", "items": {"type": "string"}},
                    "suggested_applicability": _SUGGESTED_APPLICABILITY_SCHEMA,
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
                    "merge_target_uuid",
                    "checks",
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
    last_review = dict((memory.metadata_ or {}).get("last_review") or {})
    payload: dict[str, Any] = {
        "uuid": str(memory.id),
        "uuid8": memory.uuid_short,
        "name": memory.name,
        "summary": memory.summary,
        "content": content,
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
        "previous_review": {
            "decision": last_review.get("decision"),
            "reason": last_review.get("reason"),
            "checks": last_review.get("checks"),
            "applied_remediations": last_review.get("applied_remediations"),
        }
        if last_review
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
    memory_index: list[Memory] | None = None,
    authority_prompts: list[Any] | None = None,
    authority_prompt_assignments: list[dict[str, Any]] | None = None,
    computed_tool_capabilities: str = "",
) -> str:
    """Build the bounded data payload consumed by the DB-owned curator prompt."""
    payload = [_memory_payload(memory) for memory in memories]
    governance_json = json.dumps(governance_snapshot, separators=(",", ":"), sort_keys=True)
    memories_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    corpus_json = json.dumps(
        [
            {
                "uuid": str(memory.id),
                "name": memory.name,
                "scope": memory.scope,
                "scope_id": memory.scope_id,
                "tier": TIER_REVERSE.get(int(memory.tier or 0), "reference"),
                "context_kind": memory.context_kind,
                "summary": memory.summary,
                "review_text": (
                    memory.summary
                    or (memory.metadata_ or {}).get("compact_content")
                    or " ".join((memory.content or "").split())
                ),
            }
            for memory in (memory_index or memories)
        ],
        separators=(",", ":"),
        sort_keys=True,
    )
    authority_json = json.dumps(
        [
            {
                "slug": getattr(prompt, "slug", None),
                "prompt_type": getattr(prompt, "prompt_type", None),
                "is_global": bool(getattr(prompt, "is_global", False)),
                "content": getattr(prompt, "content", ""),
            }
            for prompt in (authority_prompts or [])
        ],
        separators=(",", ":"),
        sort_keys=True,
    )
    authority_assignment_json = json.dumps(
        authority_prompt_assignments or [],
        separators=(",", ":"),
        sort_keys=True,
    )
    schema_json = json.dumps(REVIEW_SCHEMA, separators=(",", ":"), sort_keys=True)
    return (
        f"Governance snapshot JSON:\n{governance_json}\n\n"
        f"Memory batch JSON:\n{memories_json}\n\n"
        f"Active memory corpus for conflict and redundancy checks:\n{corpus_json}\n\n"
        f"Higher-authority enabled DB prompts for conflict checks:\n{authority_json}\n\n"
        "Project/profile assignments for non-global DB prompts:\n"
        f"{authority_assignment_json}\n\n"
        "Computed tool-capability block for prompt/memory redundancy checks:\n"
        f"{computed_tool_capabilities}\n\n"
        "Target by consumer_profiles for role/context and by consumer_surfaces for "
        "a specific TUI (codex, claude, pi, or gemini). Use exclude_consumer_surfaces "
        "when a durable item applies everywhere except named surfaces. Preserve existing "
        "targeting unless evidence supports a change.\n\n"
        f"Review output JSON schema:\n{schema_json}"
    )


__all__ = [
    "REVIEW_CHECK_KEYS",
    "REVIEW_SCHEMA",
    "build_memory_review_prompt",
]
