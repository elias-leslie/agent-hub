"""
Context injection service for memory-augmented completions.

Implements 3-block progressive disclosure context injection:
- Block 1 (Mandates): Always-inject golden standards (confidence=100), critical constraints
- Block 2 (Guardrails): Type-filtered anti-patterns and gotchas (TROUBLESHOOTING_GUIDE)
- Block 3 (Reference): Semantic search for patterns and workflows (CODING_STANDARD, OPERATIONAL_CONTEXT)

This ensures relevant context surfaces when needed without overwhelming
the context window.

"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .budget import BudgetUsage, count_tokens
from .context_injector_blocks import (
    get_auto_inject_references_as_search_results,
    get_guardrails,
    get_mandates,
    get_phase_triggered_references_as_search_results,
    get_triggered_references_as_search_results,
)
from .context_injector_formatter import (
    CHARS_PER_TOKEN,
    GUARDRAIL_DIRECTIVE,
    MANDATE_DIRECTIVE,
    MEMORY_CONTEXT_HEADER,
    format_context_with_reference_index,
    format_progressive_context,
    format_relevance_debug_block,
    get_context_token_stats,
    get_relevance_debug_info,
)
from .context_injector_queries import build_reference_toon_index
from .metrics_collector import InjectionMetrics, record_injection_metrics
from .service import MemoryScope, MemorySearchResult
from .settings import get_memory_settings

# Re-export for backward compatibility (used in tests)
CITATION_INSTRUCTION = "When applying a rule, cite it: Applied: [M:uuid8] or [G:uuid8]"

__all__ = [
    "CHARS_PER_TOKEN",
    "CITATION_INSTRUCTION",
    "GUARDRAIL_DIRECTIVE",
    "MANDATE_DIRECTIVE",
    "MEMORY_CONTEXT_END",
    "MEMORY_CONTEXT_HEADER",
    "MEMORY_CONTEXT_START",
    "ProgressiveContext",
    "build_progressive_context",
    "build_reference_toon_index",
    "format_context_with_reference_index",
    "format_progressive_context",
    "format_relevance_debug_block",
    "get_context_token_stats",
    "get_relevance_debug_info",
    "inject_progressive_context",
    "parse_memory_group_id",
]

logger = logging.getLogger(__name__)

# Context injection markers
MEMORY_CONTEXT_START = "<memory>"
MEMORY_CONTEXT_END = "</memory>"


@dataclass
class ProgressiveContext:
    """Result of progressive disclosure context retrieval."""

    mandates: list[MemorySearchResult] = field(default_factory=list)
    guardrails: list[MemorySearchResult] = field(default_factory=list)
    reference: list[MemorySearchResult] = field(default_factory=list)
    total_tokens: int = 0
    debug_info: dict[str, Any] = field(default_factory=dict)
    budget_usage: BudgetUsage | None = None  # Token budget tracking

    def get_loaded_uuids(self) -> list[str]:
        """Get all UUIDs that were loaded into context (for usage tracking)."""
        uuids: list[str] = []
        for m in self.mandates:
            if m.uuid:
                uuids.append(m.uuid)
        for g in self.guardrails:
            if g.uuid:
                uuids.append(g.uuid)
        for r in self.reference:
            if r.uuid:
                uuids.append(r.uuid)
        return uuids

    def get_mandate_uuids(self) -> list[str]:
        """Get mandate UUIDs (for citation tracking)."""
        return [m.uuid for m in self.mandates if m.uuid]

    def get_guardrail_uuids(self) -> list[str]:
        """Get guardrail UUIDs (for citation tracking)."""
        return [g.uuid for g in self.guardrails if g.uuid]


async def build_progressive_context(
    query: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    include_mandates: bool = True,
    include_guardrails: bool = True,
    include_global: bool = True,
    task_type: str | None = None,
    phase: str | None = None,
) -> ProgressiveContext:
    """
    Build 2-block progressive context (mandates + guardrails).

    Deterministic injection: ALL mandates and guardrails for the scope are injected.
    No scoring, no thresholds - just demotion filtering for mandates.

    Reference items are included when:
    - auto_inject=true on the episode
    - task_type is provided and matches episode's trigger_task_types
    - phase is provided and matches episode's trigger_phases

    Args:
        query: Query for context (unused for mandates/guardrails, kept for API compat)
        scope: Memory scope to query
        scope_id: Project or task ID for scoping
        include_mandates: Whether to include mandates block
        include_guardrails: Whether to include guardrails block
        include_global: Whether to also include global scope when querying project scope
        task_type: Optional task type to trigger type-specific references (e.g., "database", "frontend")
        phase: Optional subtask phase to trigger phase-specific references (e.g., "planning", "implementation")

    Returns:
        ProgressiveContext with mandates, guardrails, and triggered references
    """
    context = ProgressiveContext()

    # Determine which scopes to query
    # When scope is PROJECT and include_global=True, query both project AND global
    scopes_to_query: list[tuple[MemoryScope, str | None]] = [(scope, scope_id)]
    if include_global and scope == MemoryScope.PROJECT and scope_id:
        scopes_to_query.append((MemoryScope.GLOBAL, None))

    # Retrieve mandates, guardrails, and auto-inject references in parallel
    tasks: list[asyncio.Task[list[MemorySearchResult]]] = []
    task_keys: list[str] = []

    for query_scope, query_scope_id in scopes_to_query:
        if include_mandates:
            tasks.append(
                asyncio.create_task(
                    get_mandates(
                        scope=query_scope,
                        scope_id=query_scope_id,
                    )
                )
            )
            task_keys.append(f"mandates_{query_scope.value}")
        if include_guardrails:
            tasks.append(
                asyncio.create_task(
                    get_guardrails(
                        scope=query_scope,
                        scope_id=query_scope_id,
                    )
                )
            )
            task_keys.append(f"guardrails_{query_scope.value}")
        # Include auto-inject references (references with auto_inject=true)
        tasks.append(
            asyncio.create_task(
                get_auto_inject_references_as_search_results(
                    scope=query_scope,
                    scope_id=query_scope_id,
                )
            )
        )
        task_keys.append(f"reference_{query_scope.value}")

    # Add task_type triggered references (separate from scope loop since it uses group_id directly)
    if task_type:
        tasks.append(
            asyncio.create_task(
                get_triggered_references_as_search_results(
                    task_type=task_type,
                    group_id="global",
                )
            )
        )
        task_keys.append("reference_triggered")

    # Add phase-triggered references
    if phase:
        tasks.append(
            asyncio.create_task(
                get_phase_triggered_references_as_search_results(
                    phase=phase,
                    group_id="global",
                )
            )
        )
        task_keys.append("reference_phase_triggered")

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results from multiple scopes (project + global)
        for key, result in zip(task_keys, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("Failed to get %s: %s", key, result)
                continue

            # Extract the block type (mandates, guardrails, reference) from key
            block_type = key.split("_")[0]  # e.g., "mandates_project" -> "mandates"
            existing = getattr(context, block_type, [])

            # Merge results, avoiding duplicates by UUID
            # Type narrow: result is list[MemorySearchResult] after BaseException check
            assert isinstance(result, list)
            result_list: list[MemorySearchResult] = result
            existing_uuids = {r.uuid for r in existing}
            for item in result_list:
                if item.uuid not in existing_uuids:
                    existing.append(item)
                    existing_uuids.add(item.uuid)

            setattr(context, block_type, existing)

    # Get memory settings
    settings = await get_memory_settings()
    budget = BudgetUsage(total_budget=settings.total_budget)

    # Kill switch: if memory injection is disabled, return empty context
    if not settings.enabled:
        logger.info("Memory injection disabled - returning empty context")
        context.mandates = []
        context.guardrails = []
        context.budget_usage = budget
        context.total_tokens = 0
        return context

    # Track totals before filtering (for API response)
    budget.mandates_total = len(context.mandates)
    budget.guardrails_total = len(context.guardrails)
    budget.reference_total = len(context.reference)

    # Apply per-tier count limits (0 = unlimited)
    if settings.max_mandates > 0 and len(context.mandates) > settings.max_mandates:
        logger.info(
            "Applying mandate count limit: %d -> %d",
            len(context.mandates),
            settings.max_mandates,
        )
        context.mandates = context.mandates[: settings.max_mandates]

    if settings.max_guardrails > 0 and len(context.guardrails) > settings.max_guardrails:
        logger.info(
            "Applying guardrail count limit: %d -> %d",
            len(context.guardrails),
            settings.max_guardrails,
        )
        context.guardrails = context.guardrails[: settings.max_guardrails]

    # Count tokens for mandates and guardrails
    budget.mandates_tokens = sum(count_tokens(m.content) for m in context.mandates)
    budget.guardrails_tokens = sum(count_tokens(g.content) for g in context.guardrails)

    # Apply budget enforcement only when budget_enabled is True
    # With reference removed, mandates get 60% and guardrails get 40%
    if settings.budget_enabled:
        total_budget = settings.total_budget
        mandates_cap = int(total_budget * 0.6)
        guardrails_cap = int(total_budget * 0.4)

        # Filter mandates by budget cap
        mandates_tokens = 0
        filtered_mandates = []
        for m in context.mandates:
            tokens = count_tokens(m.content)
            if mandates_tokens + tokens <= mandates_cap:
                filtered_mandates.append(m)
                mandates_tokens += tokens
            else:
                logger.debug("Mandates tier cap hit: %d/%d tokens", mandates_tokens, mandates_cap)
                break
        context.mandates = filtered_mandates
        budget.mandates_tokens = mandates_tokens

        # Filter guardrails by budget cap
        guardrails_tokens = 0
        filtered_guardrails = []
        for g in context.guardrails:
            tokens = count_tokens(g.content)
            if guardrails_tokens + tokens <= guardrails_cap:
                filtered_guardrails.append(g)
                guardrails_tokens += tokens
            else:
                logger.debug(
                    "Guardrails tier cap hit: %d/%d tokens", guardrails_tokens, guardrails_cap
                )
                break
        context.guardrails = filtered_guardrails
        budget.guardrails_tokens = guardrails_tokens

        logger.info(
            "Budget allocation: M=%d/%d G=%d/%d",
            mandates_tokens,
            mandates_cap,
            guardrails_tokens,
            guardrails_cap,
        )
    else:
        logger.debug(
            "Budget enforcement disabled - injecting all %d memories (%d tokens)",
            len(context.mandates) + len(context.guardrails),
            budget.total_tokens,
        )

    context.budget_usage = budget
    context.total_tokens = budget.total_tokens

    # Build debug info
    context.debug_info = {
        "mandates_count": len(context.mandates),
        "guardrails_count": len(context.guardrails),
        "reference_count": len(context.reference),
        "total_tokens": context.total_tokens,
        "budget_limit": settings.total_budget,
        "budget_hit": budget.hit_limit,
        "query": query[:100] if query else "",
        "task_type": task_type,
        "phase": phase,
    }

    logger.info(
        "Progressive context: mandates=%d guardrails=%d refs=%d tokens=%d/%d%s%s%s",
        len(context.mandates),
        len(context.guardrails),
        len(context.reference),
        context.total_tokens,
        settings.total_budget,
        " (budget exceeded)" if budget.hit_limit else "",
        f" task_type={task_type}" if task_type else "",
        f" phase={phase}" if phase else "",
    )

    return context


async def inject_progressive_context(
    messages: list[dict[str, Any]],
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    query: str | None = None,
    variant: str = "BASELINE",
    session_id: str | None = None,
    external_id: str | None = None,
    project_id: str | None = None,
    collect_metrics: bool = True,
    task_type: str | None = None,
    phase: str | None = None,
) -> tuple[list[dict[str, Any]], ProgressiveContext]:
    """
    Inject mandates and guardrails context into messages.

    This is the main entry point for memory injection at SessionStart.
    Reference items are NOT injected here - use /api/memory/search for on-demand lookup.
    When task_type or phase is provided, triggered references are also injected.

    Args:
        messages: List of message dicts with role and content
        scope: Memory scope for context retrieval
        scope_id: Project or task ID for scoping
        query: Optional explicit query (kept for API compatibility)
        variant: A/B test variant (kept for API compatibility)
        session_id: Session ID for metrics tracking
        external_id: External ID (e.g., task ID) for metrics tracking
        project_id: Project ID for metrics tracking
        collect_metrics: Whether to collect injection metrics (default: True)
        task_type: Optional task type for triggered reference injection
        phase: Optional subtask phase for phase-triggered reference injection

    Returns:
        Tuple of (modified messages, ProgressiveContext with debug info)
    """
    start_time = time.monotonic()

    if not messages:
        return messages, ProgressiveContext()

    # Extract query from last user message if not provided
    if not query:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    query = content[:500]
                elif isinstance(content, list):
                    text_parts = [
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    query = " ".join(text_parts)[:500]
                break

    if not query:
        return messages, ProgressiveContext()

    # Build progressive context
    context = await build_progressive_context(
        query=query,
        scope=scope,
        scope_id=scope_id,
        task_type=task_type,
        phase=phase,
    )

    # Format context for injection
    # Get memory settings to check if reference index is enabled
    settings = await get_memory_settings()

    # Build reference TOON index if enabled
    reference_episodes: list[tuple[str, str | None, str, bool]] | None = None
    if settings.reference_index_enabled:
        reference_episodes = await build_reference_toon_index(scope, scope_id)

    # Format with full mandates/guardrails + optional TOON reference index
    formatted = format_context_with_reference_index(
        context,
        reference_episodes=reference_episodes,
        include_citations=True,
    )

    if not formatted:
        return messages, context

    # Wrap in memory context tags
    memory_block = f"{MEMORY_CONTEXT_START}\n{formatted}\n{MEMORY_CONTEXT_END}"

    # Inject into system message
    modified_messages = list(messages)
    first_msg = modified_messages[0] if modified_messages else None

    if first_msg and first_msg.get("role") == "system":
        existing_content = first_msg.get("content", "")
        modified_messages[0] = {
            "role": "system",
            "content": f"{existing_content}\n\n{memory_block}",
        }
    else:
        modified_messages.insert(0, {"role": "system", "content": memory_block})

    # Calculate injection latency
    latency_ms = int((time.monotonic() - start_time) * 1000)

    # Store variant in debug info for downstream use
    context.debug_info["variant"] = variant
    context.debug_info["injection_latency_ms"] = latency_ms

    logger.info(
        "Injected progressive context: variant=%s latency=%dms tokens=%d mandates=%d guardrails=%d",
        variant,
        latency_ms,
        context.total_tokens,
        len(context.mandates),
        len(context.guardrails),
    )

    # Collect metrics asynchronously (non-blocking)
    if collect_metrics:
        metrics = InjectionMetrics(
            injection_latency_ms=latency_ms,
            mandates_count=len(context.mandates),
            guardrails_count=len(context.guardrails),
            reference_count=0,  # Reference removed from SessionStart
            total_tokens=context.total_tokens,
            query=query,
            variant=variant,
            session_id=session_id,
            external_id=external_id,
            project_id=project_id,
            memories_loaded=context.get_loaded_uuids(),
        )
        record_injection_metrics(metrics)

    return modified_messages, context


def parse_memory_group_id(memory_group_id: str | None) -> tuple[MemoryScope, str | None]:
    """
    Parse a memory_group_id string into explicit scope and scope_id.

    Format:
    - None, "global", "default" → (GLOBAL, None)
    - "project:<id>" → (PROJECT, <id>)

    Args:
        memory_group_id: String identifier for memory group

    Returns:
        Tuple of (MemoryScope, scope_id)
    """
    if not memory_group_id or memory_group_id in ("global", "default"):
        return MemoryScope.GLOBAL, None
    if memory_group_id.startswith("project:"):
        return MemoryScope.PROJECT, memory_group_id.split(":", 1)[1]
    return MemoryScope.GLOBAL, None
