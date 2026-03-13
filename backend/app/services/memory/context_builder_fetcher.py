"""Parallel fetching logic for progressive context."""

from __future__ import annotations

import asyncio
import logging

from .context_injector_blocks import (
    get_auto_inject_references_as_search_results,
    get_guardrails,
    get_mandates,
    get_phase_triggered_references_as_search_results,
    get_triggered_references_as_search_results,
)
from .service import MemoryScope, MemorySearchResult

logger = logging.getLogger(__name__)


def _add_unique(
    items: list[MemorySearchResult],
    target: list[MemorySearchResult],
    seen: set[str],
) -> None:
    """Extend target with items not yet in seen, updating seen."""
    for item in items:
        if item.uuid not in seen:
            target.append(item)
            seen.add(item.uuid)


def _build_scope_tasks(
    scopes_to_query: list[tuple[MemoryScope, str | None]],
    include_mandates: bool,
    include_guardrails: bool,
    include_references: bool,
) -> tuple[list[asyncio.Task[list[MemorySearchResult]]], list[str]]:
    """Build parallel tasks for each scope, returning tasks and matching keys."""
    tasks: list[asyncio.Task[list[MemorySearchResult]]] = []
    task_keys: list[str] = []

    for query_scope, query_scope_id in scopes_to_query:
        if include_mandates:
            tasks.append(
                asyncio.create_task(get_mandates(scope=query_scope, scope_id=query_scope_id))
            )
            task_keys.append(f"mandates_{query_scope.value}")
        if include_guardrails:
            tasks.append(
                asyncio.create_task(get_guardrails(scope=query_scope, scope_id=query_scope_id))
            )
            task_keys.append(f"guardrails_{query_scope.value}")
        if include_references:
            tasks.append(
                asyncio.create_task(
                    get_auto_inject_references_as_search_results(
                        scope=query_scope, scope_id=query_scope_id
                    )
                )
            )
            task_keys.append(f"reference_{query_scope.value}")

    return tasks, task_keys


def _process_gathered_results(
    task_keys: list[str],
    results: list[list[MemorySearchResult] | BaseException],
) -> tuple[list[MemorySearchResult], list[MemorySearchResult], list[MemorySearchResult]]:
    """Distribute gathered results into mandates, guardrails, and reference buckets."""
    mandates: list[MemorySearchResult] = []
    guardrails: list[MemorySearchResult] = []
    reference: list[MemorySearchResult] = []

    mandates_seen: set[str] = set()
    guardrails_seen: set[str] = set()
    reference_seen: set[str] = set()

    buckets = {
        "mandates": (mandates, mandates_seen),
        "guardrails": (guardrails, guardrails_seen),
    }

    for key, result in zip(task_keys, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("Failed to get %s: %s", key, result)
            continue

        assert isinstance(result, list)
        block_type = key.split("_")[0]
        target, seen = buckets.get(block_type, (reference, reference_seen))
        _add_unique(result, target, seen)

    return mandates, guardrails, reference


async def fetch_all_episodes(
    scopes_to_query: list[tuple[MemoryScope, str | None]],
    include_mandates: bool,
    include_guardrails: bool,
    include_references: bool,
    task_type: str | None,
    phase: str | None,
) -> tuple[list[MemorySearchResult], list[MemorySearchResult], list[MemorySearchResult]]:
    """Fetch all episodes in parallel and deduplicate by UUID.

    Returns:
        Tuple of (mandates, guardrails, reference)
    """
    tasks, task_keys = _build_scope_tasks(
        scopes_to_query, include_mandates, include_guardrails, include_references
    )

    if include_references and task_type:
        tasks.append(
            asyncio.create_task(
                get_triggered_references_as_search_results(task_type=task_type, group_id="global")
            )
        )
        task_keys.append("reference_triggered")

    if include_references and phase:
        tasks.append(
            asyncio.create_task(
                get_phase_triggered_references_as_search_results(phase=phase, group_id="global")
            )
        )
        task_keys.append("reference_phase_triggered")

    if not tasks:
        return [], [], []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    return _process_gathered_results(task_keys, results)
