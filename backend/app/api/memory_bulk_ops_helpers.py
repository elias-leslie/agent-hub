"""Helper functions for memory bulk operations endpoints."""

from typing import Any

from app.services.memory.memory_utils import resolve_uuid_prefix

from .memory_schemas import BatchUpdateResult


async def resolve_ids_with_errors(
    ids: list[str],
    group_id: str = "global",
) -> tuple[list[str], list[dict[str, str]]]:
    """Resolve a list of UUID-or-prefix strings, collecting errors for failed ones.

    Returns:
        resolved_ids: list of full UUIDs that resolved successfully.
        resolution_errors: list of dicts with 'id' and 'error' for failures.
    """
    resolved_ids: list[str] = []
    resolution_errors: list[dict[str, str]] = []

    for id_or_prefix in ids:
        try:
            full_uuid = await resolve_uuid_prefix(id_or_prefix, group_id=group_id)
            resolved_ids.append(full_uuid)
        except ValueError as e:
            resolution_errors.append({"id": id_or_prefix, "error": str(e)})

    return resolved_ids, resolution_errors


async def resolve_uuids_tracking_missing(
    uuids: list[str],
    group_id: str = "global",
) -> tuple[list[str], list[str]]:
    """Resolve a list of UUID-or-prefix strings, collecting unresolved ones separately.

    Returns:
        resolved_uuids: list of full UUIDs that resolved successfully.
        unresolved: list of original identifiers that could not be resolved.
    """
    resolved_uuids: list[str] = []
    unresolved: list[str] = []

    for uuid_or_prefix in uuids:
        try:
            full_uuid = await resolve_uuid_prefix(uuid_or_prefix, group_id=group_id)
            resolved_uuids.append(full_uuid)
        except ValueError:
            unresolved.append(uuid_or_prefix)

    return resolved_uuids, unresolved


async def resolve_batch_updates(
    updates: list[Any],
    group_id: str = "global",
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Resolve UUIDs and build update dicts for batch-update items.

    Returns:
        resolved_updates: list of update dicts with full UUIDs.
        resolution_errors: mapping of original uuid/prefix -> error message.
    """
    resolved_updates: list[dict[str, Any]] = []
    resolution_errors: dict[str, str] = {}

    for item in updates:
        try:
            full_uuid = await resolve_uuid_prefix(item.uuid, group_id=group_id)
            update_dict: dict[str, Any] = {"uuid": full_uuid}

            if item.injection_tier is not None:
                update_dict["injection_tier"] = item.injection_tier.value
            if item.summary is not None:
                update_dict["summary"] = item.summary
            if item.trigger_task_types is not None:
                update_dict["trigger_task_types"] = item.trigger_task_types
            if item.pinned is not None:
                update_dict["pinned"] = item.pinned
            if item.auto_inject is not None:
                update_dict["auto_inject"] = item.auto_inject
            if item.display_order is not None:
                update_dict["display_order"] = item.display_order

            resolved_updates.append(update_dict)
        except ValueError as e:
            resolution_errors[item.uuid] = str(e)

    return resolved_updates, resolution_errors


def build_batch_update_results(
    resolved_updates: list[dict[str, Any]],
    update_results: dict[str, bool],
    resolution_errors: dict[str, str],
) -> list[BatchUpdateResult]:
    """Build the final list of BatchUpdateResult from resolved and errored updates."""
    results: list[BatchUpdateResult] = []

    for update_dict in resolved_updates:
        full_uuid = update_dict["uuid"]
        results.append(
            BatchUpdateResult(
                uuid=full_uuid,
                success=update_results.get(full_uuid, False),
                error=None if update_results.get(full_uuid) else "Episode not found",
            )
        )

    for uuid, error in resolution_errors.items():
        results.append(BatchUpdateResult(uuid=uuid, success=False, error=error))

    return results
