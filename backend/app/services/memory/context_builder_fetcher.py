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


async def fetch_all_episodes(
    scopes_to_query: list[tuple[MemoryScope, str | None]],
    include_mandates: bool,
    include_guardrails: bool,
    task_type: str | None,
    phase: str | None,
) -> tuple[list[MemorySearchResult], list[MemorySearchResult], list[MemorySearchResult]]:
    """Fetch all episodes in parallel and deduplicate by UUID.

    Returns:
        Tuple of (mandates, guardrails, reference)
    """
    tasks: list[asyncio.Task[list[MemorySearchResult]]] = []
    task_keys: list[str] = []

    # Build task list for parallel fetching
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
        tasks.append(
            asyncio.create_task(
                get_auto_inject_references_as_search_results(
                    scope=query_scope, scope_id=query_scope_id
                )
            )
        )
        task_keys.append(f"reference_{query_scope.value}")

    if task_type:
        tasks.append(
            asyncio.create_task(
                get_triggered_references_as_search_results(task_type=task_type, group_id="global")
            )
        )
        task_keys.append("reference_triggered")

    if phase:
        tasks.append(
            asyncio.create_task(
                get_phase_triggered_references_as_search_results(phase=phase, group_id="global")
            )
        )
        task_keys.append("reference_phase_triggered")

    # Fetch all in parallel
    mandates: list[MemorySearchResult] = []
    guardrails: list[MemorySearchResult] = []
    reference: list[MemorySearchResult] = []

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        mandates_uuids: set[str] = set()
        guardrails_uuids: set[str] = set()
        reference_uuids: set[str] = set()

        for key, result in zip(task_keys, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("Failed to get %s: %s", key, result)
                continue

            block_type = key.split("_")[0]
            assert isinstance(result, list)
            result_list: list[MemorySearchResult] = result

            # Add items with deduplication
            if block_type == "mandates":
                for item in result_list:
                    if item.uuid not in mandates_uuids:
                        mandates.append(item)
                        mandates_uuids.add(item.uuid)
            elif block_type == "guardrails":
                for item in result_list:
                    if item.uuid not in guardrails_uuids:
                        guardrails.append(item)
                        guardrails_uuids.add(item.uuid)
            else:  # reference
                for item in result_list:
                    if item.uuid not in reference_uuids:
                        reference.append(item)
                        reference_uuids.add(item.uuid)

    return mandates, guardrails, reference
