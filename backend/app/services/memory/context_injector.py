"""
Context injection service for memory-augmented completions.

Implements hybrid two-tier context injection:
- Tier 1 (Global): System design + domain knowledge at task start
- Tier 2 (JIT): Patterns + gotchas at subtask execution time

This ensures relevant context surfaces when needed without overwhelming
the context window.
"""

import logging
from enum import Enum
from typing import Any

from .service import (
    MemoryCategory,
    MemoryScope,
    MemorySearchResult,
    get_memory_service,
)

logger = logging.getLogger(__name__)

# Context injection markers
MEMORY_CONTEXT_START = "<memory>"
MEMORY_CONTEXT_END = "</memory>"

# Maximum approximate tokens for context injection (rough estimate: 4 chars = 1 token)
MAX_CONTEXT_TOKENS = 2000
CHARS_PER_TOKEN = 4
MAX_CONTEXT_CHARS = MAX_CONTEXT_TOKENS * CHARS_PER_TOKEN


class ContextTier(str, Enum):
    """Context injection tier."""

    GLOBAL = "global"  # Task-start: system_design, domain_knowledge
    JIT = "jit"  # Subtask-time: patterns, gotchas (troubleshooting_guide, coding_standard)
    BOTH = "both"  # Combined for single-shot requests


# Directive language for global context
GLOBAL_CONTEXT_DIRECTIVE = """
## Project Context (from memory)

The following context has been retrieved from your knowledge base about this project.
Use this information to inform your decisions and recommendations.
"""

# Directive language for JIT context
JIT_CONTEXT_DIRECTIVE = """
## Relevant Patterns & Known Issues

The following patterns and gotchas have been retrieved based on the current task.
Pay special attention to the gotchas to avoid repeating past mistakes.
"""


def _truncate_by_score(
    results: list[MemorySearchResult],
    max_chars: int,
) -> list[MemorySearchResult]:
    """
    Truncate results by relevance score to fit within character limit.

    Args:
        results: List of search results with scores
        max_chars: Maximum total characters

    Returns:
        Truncated list fitting within limit
    """
    # Sort by score descending
    sorted_results = sorted(results, key=lambda r: r.relevance_score, reverse=True)

    truncated = []
    current_chars = 0

    for result in sorted_results:
        content_chars = len(result.content)
        if current_chars + content_chars > max_chars:
            break
        truncated.append(result)
        current_chars += content_chars

    return truncated


async def build_global_context(
    scope: MemoryScope = MemoryScope.PROJECT,
    scope_id: str | None = None,
    task_description: str | None = None,
    max_results: int = 10,
) -> str:
    """
    Build global context for task-start injection.

    Retrieves system design and domain knowledge relevant to the task.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID
        task_description: Optional task description to improve search relevance
        max_results: Maximum results to include

    Returns:
        Formatted context string for system prompt injection
    """
    service = get_memory_service(scope=scope, scope_id=scope_id)

    query = task_description or "project architecture system design domain knowledge"

    # Search for system design content
    try:
        edges = await service._graphiti.search(
            query=f"system design architecture: {query}",
            group_ids=[service._group_id],
            num_results=max_results,
        )
    except Exception as e:
        logger.warning("Failed to search for global context: %s", e)
        return ""

    # Filter for relevant categories and build results
    relevant_categories = {MemoryCategory.SYSTEM_DESIGN, MemoryCategory.DOMAIN_KNOWLEDGE}
    results: list[MemorySearchResult] = []

    for edge in edges:
        source_desc = getattr(edge, "source_description", "") or ""
        name = getattr(edge, "name", "") or ""
        category = service._infer_category(source_desc, name)

        if category in relevant_categories:
            results.append(
                MemorySearchResult(
                    uuid=edge.uuid,
                    content=edge.fact or "",
                    source=service._map_episode_type(getattr(edge, "source", None)),
                    relevance_score=getattr(edge, "score", 1.0),
                    created_at=edge.created_at,
                    facts=[edge.fact] if edge.fact else [],
                )
            )

    if not results:
        return ""

    # Truncate to fit within limit
    truncated = _truncate_by_score(results, MAX_CONTEXT_CHARS // 2)  # Half for global

    # Format context
    parts = [GLOBAL_CONTEXT_DIRECTIVE.strip(), "", MEMORY_CONTEXT_START]

    if truncated:
        parts.append("### System & Domain Knowledge")
        for r in truncated:
            parts.append(f"- {r.content}")

    parts.append(MEMORY_CONTEXT_END)
    return "\n".join(parts)


async def build_subtask_context(
    subtask_description: str,
    scope: MemoryScope = MemoryScope.PROJECT,
    scope_id: str | None = None,
    max_results: int = 10,
) -> str:
    """
    Build JIT context for subtask execution.

    Retrieves patterns and gotchas relevant to the specific subtask.

    Args:
        subtask_description: Description of the subtask being executed
        scope: Memory scope to query
        scope_id: Project or task ID
        max_results: Maximum results per category

    Returns:
        Formatted context string for injection
    """
    service = get_memory_service(scope=scope, scope_id=scope_id)

    # Get patterns and gotchas using the dedicated method
    try:
        patterns, gotchas = await service.get_patterns_and_gotchas(
            query=subtask_description,
            num_results=max_results,
            min_score=0.4,
        )
    except Exception as e:
        logger.warning("Failed to get patterns/gotchas: %s", e)
        return ""

    if not patterns and not gotchas:
        return ""

    # Truncate combined results
    combined = patterns + gotchas
    truncated = _truncate_by_score(combined, MAX_CONTEXT_CHARS // 2)

    # Separate back into patterns and gotchas
    truncated_patterns = [r for r in truncated if r in patterns]
    truncated_gotchas = [r for r in truncated if r in gotchas]

    # Format context
    parts = [JIT_CONTEXT_DIRECTIVE.strip(), "", MEMORY_CONTEXT_START]

    if truncated_patterns:
        parts.append("### Relevant Patterns")
        for p in truncated_patterns:
            parts.append(f"- {p.content}")

    if truncated_gotchas:
        parts.append("")
        parts.append("### Known Gotchas (IMPORTANT)")
        for g in truncated_gotchas:
            parts.append(f"- ⚠️ {g.content}")

    parts.append(MEMORY_CONTEXT_END)
    return "\n".join(parts)


def parse_memory_group_id(memory_group_id: str | None) -> tuple[MemoryScope, str | None]:
    """
    Parse a memory_group_id string into explicit scope and scope_id.

    Format:
    - None, "global", "default" → (GLOBAL, None)
    - "project:<id>" → (PROJECT, <id>)
    - "task:<id>" → (TASK, <id>)

    Args:
        memory_group_id: String identifier for memory group

    Returns:
        Tuple of (MemoryScope, scope_id)
    """
    if not memory_group_id or memory_group_id in ("global", "default"):
        return MemoryScope.GLOBAL, None
    if memory_group_id.startswith("project:"):
        return MemoryScope.PROJECT, memory_group_id.split(":", 1)[1]
    if memory_group_id.startswith("task:"):
        return MemoryScope.TASK, memory_group_id.split(":", 1)[1]
    # Explicit project scope requires "project:" prefix
    # Bare strings default to GLOBAL for cross-session knowledge transfer
    return MemoryScope.GLOBAL, None


async def inject_memory_context(
    messages: list[dict[str, Any]],
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    tier: ContextTier = ContextTier.BOTH,
    task_description: str | None = None,
    subtask_description: str | None = None,
    max_facts: int = 10,
) -> tuple[list[dict[str, Any]], int]:
    """
    Inject relevant memory context into messages.

    Supports hybrid two-tier injection:
    - GLOBAL tier: System design and domain knowledge at task start
    - JIT tier: Patterns and gotchas for specific subtasks
    - BOTH tier: Combined context for single-shot requests

    Args:
        messages: List of message dicts with role and content
        scope: Memory scope for context retrieval (default: GLOBAL)
        scope_id: Project or task ID for scoping (only needed for PROJECT/TASK scope)
        tier: Which context tier to inject
        task_description: Task description for global context search
        subtask_description: Subtask description for JIT context search
        max_facts: Maximum facts to include per tier

    Returns:
        Tuple of (modified messages, number of items injected)
    """
    if not messages:
        return messages, 0

    context_parts: list[str] = []
    items_count = 0

    # Build context based on tier
    if tier in (ContextTier.GLOBAL, ContextTier.BOTH):
        # Determine task description from messages if not provided
        effective_task_desc = task_description
        if not effective_task_desc:
            for msg in messages:
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        effective_task_desc = content[:500]  # Use first 500 chars
                    break

        global_ctx = await build_global_context(
            scope=scope,
            scope_id=scope_id,
            task_description=effective_task_desc,
            max_results=max_facts,
        )
        if global_ctx:
            context_parts.append(global_ctx)
            items_count += 1

    if tier in (ContextTier.JIT, ContextTier.BOTH):
        # Use subtask_description or extract from last user message
        effective_subtask_desc = subtask_description
        if not effective_subtask_desc:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        effective_subtask_desc = content
                    elif isinstance(content, list):
                        text_parts = [
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict) and block.get("type") == "text"
                        ]
                        effective_subtask_desc = " ".join(text_parts)
                    break

        if effective_subtask_desc:
            jit_ctx = await build_subtask_context(
                subtask_description=effective_subtask_desc,
                scope=scope,
                scope_id=scope_id,
                max_results=max_facts,
            )
            if jit_ctx:
                context_parts.append(jit_ctx)
                items_count += 1

    if not context_parts:
        logger.debug("No memory context found for injection")
        return messages, 0

    # Combine context parts
    full_context = "\n\n".join(context_parts)

    # Inject into system message
    modified_messages = list(messages)
    first_msg = modified_messages[0] if modified_messages else None

    if first_msg and first_msg.get("role") == "system":
        existing_content = first_msg.get("content", "")
        modified_messages[0] = {
            "role": "system",
            "content": f"{existing_content}\n\n{full_context}",
        }
    else:
        modified_messages.insert(0, {"role": "system", "content": full_context})

    logger.info(
        "Injected memory context: tier=%s, scope=%s, items=%d",
        tier.value,
        scope.value,
        items_count,
    )

    return modified_messages, items_count
