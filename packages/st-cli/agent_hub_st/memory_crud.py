"""CRUD operations for memory system."""

from __future__ import annotations

from collections.abc import Callable

import typer
from st_sdk.context import OutputContext
from st_sdk.output import output_error, output_json

from ._api_paths import (
    CONTEXT_INVENTORY_PATH,
    CONTEXT_SAVE_PATH,
    MEMORY_BATCH_GET_PATH,
    MEMORY_BULK_DELETE_PATH,
    MEMORY_BULK_TAG_PATH,
    MEMORY_EPISODE_PATH,
    MEMORY_EPISODE_RESTORE_PATH,
    MEMORY_EPISODE_REVISIONS_PATH,
    MEMORY_LIST_PATH,
    MEMORY_PROGRESSIVE_CONTEXT_PATH,
    MEMORY_SAVE_LEARNING_PATH,
    MEMORY_SEARCH_PATH,
    MEMORY_STATS_PATH,
)
from ._memory_crud_helpers import (
    _validate_update_and_normalize,
    build_save_payload,
    fetch_episode_tags,
    fetch_existing_episode,
    merge_applicability_payload,
    parse_tags_csv,
    patch_episode_properties,
    replace_episode_tags,
    update_episode_content_or_tier,
    validate_save_inputs,
)
from .memory_api import agent_hub_request
from .memory_formatters import (
    format_batch_get_compact,
    format_get_compact,
    format_list_compact,
    format_restore_compact,
    format_revisions_compact,
    format_save_compact,
    format_search_compact,
    format_stats_compact,
)
from .memory_validation import validate_content_format, validate_episode_content_present


def _emit(out: OutputContext, result: dict[str, object], compact_fn: Callable[[dict[str, object]], None]) -> None:
    if out.is_compact:
        compact_fn(result)
    else:
        output_json(result)


def _resolve_existing_state(
    uuid: str,
    content: str | None,
    normalized_tier: str | None,
    replacement_tags: list[str] | None,
) -> tuple[dict[str, object] | None, str | None, str, list[str]]:
    if content is None and normalized_tier is None:
        return None, normalized_tier, uuid, []
    existing = fetch_existing_episode(uuid)
    effective_tier = normalized_tier or str(existing.get("injection_tier", "reference"))
    target_uuid = str(existing.get("uuid", uuid))
    existing_tags = fetch_episode_tags(uuid) if replacement_tags is None else []
    return existing, effective_tier, target_uuid, existing_tags


def stats_impl(
    out: OutputContext,
    scope: str,
    scope_id: str | None,
    all_groups: bool = False,
) -> None:
    params = {"all_groups": "true"} if all_groups else None
    result = agent_hub_request(
        "GET",
        MEMORY_STATS_PATH,
        params=params,
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory stats",
    )
    if isinstance(result, dict) and all_groups:
        result["scope"] = "all"
    _emit(out, result, format_stats_compact)


def status_impl(
    out: OutputContext,
    scope: str,
    scope_id: str | None,
    consumer_profile: str,
    current_branch: str | None,
) -> bool:
    """Probe progressive-context health through the live Agent Hub path."""
    params: dict[str, object] = {
        "query": "memory status probe",
        "consumer_profile": consumer_profile,
    }
    if current_branch:
        params["current_branch"] = current_branch
    result = agent_hub_request(
        "GET",
        MEMORY_PROGRESSIVE_CONTEXT_PATH,
        params=params,
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory status",
        retries=3,
    )
    summary = {
        "healthy": result.get("status", "ok") == "ok",
        "status": result.get("status", "ok"),
        "scope": scope,
        "scope_id": scope_id,
        "consumer_profile": consumer_profile,
        "attempts": result.get("attempts", 1),
        "latency_ms": result.get("latency_ms", 0),
        "failure": result.get("failure"),
    }
    if out.is_compact:
        health = "OK" if summary["healthy"] else "FAILED"
        typer.echo(
            f"memory={health} scope={scope} scope_id={scope_id or '-'} "
            f"profile={consumer_profile} attempts={summary['attempts']} latency_ms={summary['latency_ms']}"
        )
        failure = summary.get("failure")
        if isinstance(failure, dict):
            typer.echo(
                f"failure={failure.get('error_type', 'unknown')} "
                f"operation={failure.get('operation', 'progressive-context')} "
                f"message={failure.get('error_message', '')}"
            )
        return bool(summary["healthy"])
    output_json(summary)
    return bool(summary["healthy"])


def validate_write_scope(scope: str | None, scope_id: str | None) -> tuple[str, str | None]:
    """Require a deliberate scope, never silently broaden a write to global."""
    if scope not in {"global", "project", "agent"}:
        raise typer.BadParameter("Choose explicit --scope global, project, or agent; project/agent scope requires --scope-id.")
    target = scope_id.strip() if scope_id else None
    if scope == "global" and scope_id is not None:
        raise typer.BadParameter("Global scope cannot have --scope-id.")
    if scope != "global" and not target:
        raise typer.BadParameter("Project/agent scope requires a non-empty --scope-id.")
    return scope, target


def retarget_memory(uuid: str, scope: str, scope_id: str | None, reason: str | None) -> None:
    """Use the existing audited context editor, preserving all other policy fields."""
    context = {"consumer_surface": "st", "consumer_profile": "agent_startup"}
    view = agent_hub_request("POST", CONTEXT_INVENTORY_PATH, json=context, tool_name="st memory update")
    matches = [source for source in view["sources"] if source["source_type"] == "memory" and source["source_id"].startswith(uuid)]
    if len(matches) != 1:
        raise typer.BadParameter("Memory UUID must identify exactly one source; use its full UUID.")
    source = matches[0]
    policy = {**source["policy"], "scope": scope, "targets": [scope_id] if scope_id else []}
    result = agent_hub_request("POST", CONTEXT_SAVE_PATH, tool_name="st memory update", json={
        "context": context, "reason": reason or "Correct memory scope through ST",
        "edits": [{"source_type": "memory", "source_id": source["source_id"], "expected_revision": source["revision"], "policy": policy}],
    })
    typer.echo(f"Scope: {scope}:{scope_id or '-'} change={result['change_id']}")


def save_impl(
    out: OutputContext, content: str, summary: str, tier: str, confidence: int,
    context: str | None, pinned: bool, trigger_types: str | None, trigger_phases: str | None,
    context_kind: str | None, consumer_profiles: str | None, exclude_consumer_profiles: str | None,
    agent_slugs: str | None, exclude_agent_slugs: str | None, audience_tags: str | None,
    exclude_audience_tags: str | None, tags: str | None, scope: str | None, scope_id: str | None,
    change_reason: str | None = None, render_mode: str | None = None,
) -> None:
    summary = validate_save_inputs(tier, confidence, summary)
    validate_episode_content_present(content)
    validate_content_format(content, summary, tier)
    scope, scope_id = validate_write_scope(scope, scope_id)
    payload = build_save_payload(
        content, summary, tier, confidence, context, pinned, trigger_types, trigger_phases,
        context_kind, consumer_profiles, exclude_consumer_profiles, agent_slugs, exclude_agent_slugs,
        audience_tags, exclude_audience_tags, change_reason, render_mode=render_mode,
    )
    result = agent_hub_request(
        "POST", MEMORY_SAVE_LEARNING_PATH, json=payload,
        scope=scope, scope_id=scope_id, tool_name="st memory save",
    )
    parsed_tags = parse_tags_csv(tags)
    if parsed_tags is not None and result.get("uuid"):
        replace_episode_tags(str(result["uuid"]), parsed_tags)
    _emit(out, result, format_save_compact)


def list_impl(
    out: OutputContext, limit: int, cursor: str | None, tier: str | None,
    scope: str, scope_id: str | None,
) -> None:
    params: dict[str, object] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    if tier:
        params["category"] = tier
    result = agent_hub_request(
        "GET", MEMORY_LIST_PATH, params=params,
        scope=scope, scope_id=scope_id, tool_name="st memory list",
    )
    _emit(out, result, format_list_compact)


def search_impl(
    out: OutputContext, query: str, limit: int, min_score: float,
    tier: str | None, scope: str, scope_id: str | None,
) -> None:
    params: dict[str, object] = {"query": query, "limit": limit, "min_score": min_score}
    if tier:
        params["category"] = tier
    result = agent_hub_request(
        "GET", MEMORY_SEARCH_PATH, params=params,
        scope=scope, scope_id=scope_id, tool_name="st memory search",
    )
    _emit(out, result, format_search_compact)


def get_impl(out: OutputContext, uuids: list[str]) -> None:
    if not uuids:
        output_error("At least one UUID required")
        raise typer.Exit(1)

    if len(uuids) > 1:
        result = agent_hub_request(
            "POST", MEMORY_BATCH_GET_PATH, json={"uuids": uuids}, tool_name="st memory get"
        )
        _emit(out, result, format_batch_get_compact)
        return

    result = agent_hub_request("GET", MEMORY_EPISODE_PATH.format(uuid=uuids[0]), tool_name="st memory get")
    _emit(out, result, format_get_compact)


def delete_impl(uuids: list[str], *, change_reason: str | None = None) -> None:
    if len(uuids) == 1:
        _delete_single(uuids[0], change_reason=change_reason)
        return
    result = agent_hub_request(
        "POST", MEMORY_BULK_DELETE_PATH,
        json={"ids": uuids, "change_reason": change_reason},
        tool_name="st memory delete",
    )
    for error in result.get("errors", []):
        typer.echo(f"Failed: {error['id'][:8]} - {error.get('error', 'Unknown')}")
    typer.echo(f"\nDeleted: {result.get('deleted', 0)}, Failed: {result.get('failed', 0)}")


def _delete_single(uuid: str, *, change_reason: str | None = None) -> None:
    result = agent_hub_request(
        "DELETE", MEMORY_EPISODE_PATH.format(uuid=uuid),
        params={"change_reason": change_reason} if change_reason else None,
        tool_name="st memory delete",
    )
    if result.get("success"):
        typer.echo(f"Deleted: {uuid[:8]}")
        typer.echo("\nDeleted: 1, Failed: 0")
    else:
        typer.echo(f"Failed: {uuid[:8]} - {result.get('detail', 'Unknown error')}")
        typer.echo("\nDeleted: 0, Failed: 1")


def _apply_properties_patch(
    target_uuid: str, existing: dict[str, object] | None, uuid: str,
    normalized_summary: str | None, trigger_types: str | None, trigger_phases: str | None,
    pinned: bool | None, context_kind: str | None, app_fields: tuple[str | None, ...],
    clear_applicability: bool, change_reason: str | None,
    render_mode: str | None = None,
) -> bool:
    consumer_profiles, exclude_consumer_profiles, agent_slugs, exclude_agent_slugs, audience_tags, exclude_audience_tags = app_fields
    applicability_changed = any(f is not None for f in app_fields) or clear_applicability
    if not (
        any(
            f is not None
            for f in (normalized_summary, trigger_types, trigger_phases, pinned, context_kind, render_mode)
        )
        or applicability_changed
    ):
        return False
    applicability = None
    if applicability_changed:
        existing = existing if existing is not None else fetch_existing_episode(uuid)
        applicability = merge_applicability_payload(
            existing,
            consumer_profiles=consumer_profiles, exclude_consumer_profiles=exclude_consumer_profiles,
            agent_slugs=agent_slugs, exclude_agent_slugs=exclude_agent_slugs,
            audience_tags=audience_tags, exclude_audience_tags=exclude_audience_tags,
            clear_applicability=clear_applicability,
        )
    if change_reason:
        patch_episode_properties(
            target_uuid, normalized_summary, trigger_types, trigger_phases,
            pinned, context_kind, applicability,
            change_reason=change_reason, render_mode=render_mode,
        )
    else:
        patch_episode_properties(
            target_uuid, normalized_summary, trigger_types, trigger_phases,
            pinned, context_kind, applicability, render_mode=render_mode,
        )
    return True


def update_impl(
    uuid: str, content: str | None, tier: str | None, summary: str | None,
    trigger_types: str | None, trigger_phases: str | None, pinned: bool | None,
    context_kind: str | None, consumer_profiles: str | None, exclude_consumer_profiles: str | None,
    agent_slugs: str | None, exclude_agent_slugs: str | None, audience_tags: str | None,
    exclude_audience_tags: str | None, clear_applicability: bool, tags: str | None,
    clear_tags: bool, change_reason: str | None = None, render_mode: str | None = None,
    *, scope: str | None = None, scope_id: str | None = None,
) -> None:
    if scope is not None or scope_id is not None:
        scope, scope_id = validate_write_scope(scope, scope_id)
    normalized_summary, normalized_tier, replacement_tags, normalized_render_mode = _validate_update_and_normalize(
        content, tier, summary, tags, clear_tags, clear_applicability, trigger_types, trigger_phases,
        pinned, context_kind, consumer_profiles, exclude_consumer_profiles, agent_slugs,
        exclude_agent_slugs, audience_tags, exclude_audience_tags, render_mode=render_mode, scope=scope,
    )
    existing, effective_tier, target_uuid, existing_tags = _resolve_existing_state(
        uuid, content, normalized_tier, replacement_tags
    )
    if content is not None:
        existing_summary = str(existing.get("summary", "")) if existing is not None else ""
        validate_content_format(content, normalized_summary or existing_summary, effective_tier or "reference")
    if scope is not None:
        retarget_memory(uuid, scope, scope_id, change_reason)
    content_or_tier_changed = content is not None or normalized_tier is not None
    tags_changed = replacement_tags is not None or clear_tags
    if content_or_tier_changed:
        update_episode_content_or_tier(
            target_uuid,
            content=content,
            tier=effective_tier,
            change_reason=change_reason,
        )
        replace_episode_tags(target_uuid, replacement_tags if replacement_tags is not None else existing_tags)
    _app = (consumer_profiles, exclude_consumer_profiles, agent_slugs, exclude_agent_slugs, audience_tags, exclude_audience_tags)
    properties_patched = _apply_properties_patch(
        target_uuid, existing, uuid, normalized_summary, trigger_types, trigger_phases,
        pinned, context_kind, _app, clear_applicability, change_reason,
        render_mode=normalized_render_mode,
    )
    if not content_or_tier_changed and tags_changed:
        replace_episode_tags(target_uuid, replacement_tags or [])
    if not content_or_tier_changed and not properties_patched and not tags_changed and scope is None:
        typer.echo("No changes made.")


def tag_impl(uuids: list[str], *, add_tags: str | None, remove_tags: str | None) -> None:
    """Add/remove tags across one or more memory episodes."""
    parsed_add_tags = parse_tags_csv(add_tags) or []
    parsed_remove_tags = parse_tags_csv(remove_tags) or []
    if not parsed_add_tags and not parsed_remove_tags:
        typer.echo("Error: Must specify --add-tags and/or --remove-tags")
        raise typer.Exit(1)

    result = agent_hub_request(
        "POST", MEMORY_BULK_TAG_PATH,
        json={"uuids": uuids, "add_tags": parsed_add_tags, "remove_tags": parsed_remove_tags},
        tool_name="st memory tag",
    )
    typer.echo(f"Tagged: updated={result.get('updated', 0)} failed={result.get('failed', 0)}")


def revisions_impl(out: OutputContext, uuid: str, limit: int) -> None:
    """Fetch immutable revision history for one memory episode."""
    result = agent_hub_request(
        "GET", MEMORY_EPISODE_REVISIONS_PATH.format(uuid=uuid), params={"limit": limit},
        tool_name="st memory revisions",
    )
    _emit(out, result, lambda r: format_revisions_compact(uuid, r))


def restore_impl(uuid: str, revision_id: str, *, change_reason: str | None = None) -> None:
    """Restore a memory episode to one historical revision."""
    payload = {"change_reason": change_reason} if change_reason else {}
    result = agent_hub_request(
        "POST", MEMORY_EPISODE_RESTORE_PATH.format(uuid=uuid, revision_id=revision_id),
        json=payload, tool_name="st memory restore",
    )
    format_restore_compact(uuid, revision_id, result)
