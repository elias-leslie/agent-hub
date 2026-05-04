"""Dedicated agent review loop for memory quality and assignment.

This facade preserves the public import surface while focused modules own
prompt construction, decision parsing, and batch execution.
"""

from __future__ import annotations

from ._review_agent_apply import _apply_decision
from ._review_agent_call import _call_reviewer_agent
from ._review_agent_decisions import (
    MIN_COMPACT_REVIEW_CONTENT_CHARS,
    MemoryReviewBatchResult,
    MemoryReviewDecision,
    _normalize_compact_content,
    parse_memory_review_content,
)
from ._review_agent_prompt import (
    REVIEW_SCHEMA,
    build_memory_review_prompt,
)
from ._review_agent_runner import (
    DEFAULT_BATCH_LIMIT,
    DEFAULT_REVIEW_CADENCE_DAYS,
    DEFAULT_REVIEWER_AGENT,
    run_memory_review_batch,
    select_memories_due_for_review,
)
from .governance import collect_memory_governance_snapshot

__all__ = [
    "DEFAULT_BATCH_LIMIT",
    "DEFAULT_REVIEWER_AGENT",
    "DEFAULT_REVIEW_CADENCE_DAYS",
    "MIN_COMPACT_REVIEW_CONTENT_CHARS",
    "REVIEW_SCHEMA",
    "MemoryReviewBatchResult",
    "MemoryReviewDecision",
    "_apply_decision",
    "_call_reviewer_agent",
    "_normalize_compact_content",
    "build_memory_review_prompt",
    "collect_memory_governance_snapshot",
    "parse_memory_review_content",
    "run_memory_review_batch",
    "select_memories_due_for_review",
]
