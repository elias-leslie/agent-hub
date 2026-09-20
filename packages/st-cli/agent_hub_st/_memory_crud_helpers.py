"""Helper functions for memory CRUD operations."""

from __future__ import annotations

import typer

from ._api_paths import (
    MEMORY_EPISODE_PATH,
    MEMORY_EPISODE_PROPERTIES_PATH,
    MEMORY_EPISODE_TAGS_PATH,
)
from .memory_api import agent_hub_request
from .memory_validation import validate_episode_content_present, validate_summary_length

VALID_TIERS = ("mandate", "guardrail", "reference")
VALID_CONTEXT_KINDS = ("policy", "reference", "capability", "continuity", "signal")
VALID_RENDER_MODES = ("full", "compact", "summary")
RENDER_MODE_CLEAR_ALIASES = ("auto", "clear", "none")

# Sentinel returned by validate_render_mode_input to mean "clear the field"
# (distinct from None which means "leave unchanged").
RENDER_MODE_CLEAR = "__RENDER_MODE_CLEAR__"

_APPLICABILITY_KEYS = (
    "consumer_profiles", "exclude_consumer_profiles",
    "agent_slugs", "exclude_agent_slugs",
    "audience_tags", "exclude_audience_tags",
)


def parse_csv_values(raw: str | None) -> list[str] | None:
    """Parse comma-separated values, preserving order while deduplicating."""
    if raw is None:
        return None
    seen: set[str] = set()
    result: list[str] = []
    for part in raw.split(","):
        v = part.strip()
        if v and v not in seen:
            seen.add(v)
            result.append(v)
    return result


def validate_tier(tier: str) -> str:
    """Validate tier value and return the normalized string."""
    from st_sdk.output import output_error
    normalized = tier.strip()
    if normalized not in VALID_TIERS:
        output_error(f"Invalid tier: {tier}. Must be mandate, guardrail, or reference.")
        raise typer.Exit(1)
    return normalized


def validate_context_kind(context_kind: str) -> str:
    """Validate context kind value and return the normalized string."""
    from st_sdk.output import output_error
    normalized = context_kind.strip()
    if normalized not in VALID_CONTEXT_KINDS:
        output_error(
            f"Invalid context kind: {context_kind}. Must be policy, reference, capability, continuity, or signal."
        )
        raise typer.Exit(1)
    return normalized


def validate_render_mode_input(value: str | None, *, allow_clear: bool) -> str | None:
    """Validate --render-mode input.

    Returns None if value is None (unset). Returns RENDER_MODE_CLEAR sentinel when
    the user explicitly asked to clear (only valid when allow_clear=True). Returns
    the normalized 'full' / 'compact' / 'summary' otherwise. Exits on invalid input.
    """
    from st_sdk.output import output_error
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        output_error("--render-mode cannot be blank.")
        raise typer.Exit(1)
    if normalized in RENDER_MODE_CLEAR_ALIASES:
        if not allow_clear:
            output_error(
                "--render-mode 'auto' / 'clear' is only valid for update; omit the flag for save."
            )
            raise typer.Exit(1)
        return RENDER_MODE_CLEAR
    if normalized not in VALID_RENDER_MODES:
        output_error(
            f"Invalid --render-mode: {value}. Must be full, compact, summary"
            + (", or auto/clear." if allow_clear else ".")
        )
        raise typer.Exit(1)
    return normalized


def validate_summary_input(summary: str, *, required: bool) -> str:
    """Normalize summary text and enforce presence and max length."""
    from st_sdk.output import output_error
    normalized = summary.strip()
    if required and not normalized:
        output_error("--summary is required. Provide a short action phrase (~35 chars).")
        raise typer.Exit(1)
    if not normalized:
        output_error("Summary cannot be blank.")
        raise typer.Exit(1)
    validate_summary_length(normalized)
    return normalized


def parse_tags_csv(tags: str | None) -> list[str] | None:
    """Parse comma-separated tags into a deduplicated list."""
    return parse_csv_values(tags)


def validate_save_inputs(tier: str, confidence: int, summary: str) -> str:
    """Validate save inputs and return stripped summary, raise on error."""
    from st_sdk.output import output_error
    validate_tier(tier)
    if confidence < 0 or confidence > 100:
        output_error(f"Invalid confidence: {confidence}. Must be 0-100.")
        raise typer.Exit(1)
    return validate_summary_input(summary, required=True)


def build_applicability_payload(
    *, consumer_profiles: str | None, exclude_consumer_profiles: str | None,
    agent_slugs: str | None, exclude_agent_slugs: str | None,
    audience_tags: str | None, exclude_audience_tags: str | None,
) -> dict[str, list[str]] | None:
    """Build applicability payload from CLI CSV options."""
    raw = (consumer_profiles, exclude_consumer_profiles, agent_slugs,
           exclude_agent_slugs, audience_tags, exclude_audience_tags)
    applicability = {k: parse_csv_values(v) or [] for k, v in zip(_APPLICABILITY_KEYS, raw, strict=True)}
    return applicability if any(applicability.values()) else None


def build_save_payload(
    content: str, summary: str, tier: str, confidence: int,
    context: str | None, pinned: bool,
    trigger_types: str | None, trigger_phases: str | None, context_kind: str | None,
    consumer_profiles: str | None, exclude_consumer_profiles: str | None,
    agent_slugs: str | None, exclude_agent_slugs: str | None,
    audience_tags: str | None, exclude_audience_tags: str | None,
    change_reason: str | None,
    render_mode: str | None = None,
) -> dict[str, object]:
    """Build the payload dict for save-learning request."""
    payload: dict[str, object] = {
        "content": content, "injection_tier": tier,
        "confidence": confidence, "summary": summary,
    }
    if context:
        payload["context"] = context
    if pinned:
        payload["pinned"] = True
    if trigger_types:
        parsed = parse_csv_values(trigger_types)
        if parsed:
            payload["trigger_task_types"] = parsed
    if trigger_phases is not None:
        payload["trigger_phases"] = parse_csv_values(trigger_phases) or []
    if context_kind is not None:
        payload["context_kind"] = validate_context_kind(context_kind)
    if render_mode is not None:
        # save flow: cannot clear, value must be full/compact/summary
        normalized = validate_render_mode_input(render_mode, allow_clear=False)
        if normalized is not None:
            payload["render_mode"] = normalized
    applicability = build_applicability_payload(
        consumer_profiles=consumer_profiles, exclude_consumer_profiles=exclude_consumer_profiles,
        agent_slugs=agent_slugs, exclude_agent_slugs=exclude_agent_slugs,
        audience_tags=audience_tags, exclude_audience_tags=exclude_audience_tags,
    )
    if applicability is not None:
        payload["applicability"] = applicability
    if change_reason:
        payload["change_reason"] = change_reason
    return payload


def merge_applicability_payload(
    existing_episode: dict[str, object] | None, *,
    consumer_profiles: str | None, exclude_consumer_profiles: str | None,
    agent_slugs: str | None, exclude_agent_slugs: str | None,
    audience_tags: str | None, exclude_audience_tags: str | None,
    clear_applicability: bool,
) -> dict[str, list[str]] | None:
    """Merge CLI applicability updates with an existing episode payload."""
    if clear_applicability:
        return {}
    existing_raw = existing_episode.get("applicability") if isinstance(existing_episode, dict) else {}
    base = dict(existing_raw) if isinstance(existing_raw, dict) else {}
    merged: dict[str, list[str]] = {k: list(base.get(k) or []) for k in _APPLICABILITY_KEYS}
    raw_updates = (consumer_profiles, exclude_consumer_profiles, agent_slugs,
                   exclude_agent_slugs, audience_tags, exclude_audience_tags)
    for key, raw in zip(_APPLICABILITY_KEYS, raw_updates, strict=True):
        if raw is not None:
            merged[key] = parse_csv_values(raw) or []
    return merged


def fetch_existing_episode(uuid: str) -> dict[str, object]:
    """Fetch an existing episode, raising on error."""
    return agent_hub_request("GET", MEMORY_EPISODE_PATH.format(uuid=uuid), tool_name="st memory update")


def fetch_episode_tags(uuid: str) -> list[str]:
    """Fetch current tags for an episode."""
    result = agent_hub_request("GET", MEMORY_EPISODE_TAGS_PATH.format(uuid=uuid), tool_name="st memory update")
    return [str(tag) for tag in result.get("tags", [])]


def update_episode_content_or_tier(
    episode_uuid: str, *, content: str | None, tier: str | None,
    change_reason: str | None = None,
) -> None:
    """Patch episode content and/or tier in place while preserving UUID."""
    payload: dict[str, object] = {}
    if content is not None:
        payload["content"] = content
    if tier is not None:
        payload["injection_tier"] = tier
    if change_reason:
        payload["change_reason"] = change_reason
    result = agent_hub_request(
        "PATCH", MEMORY_EPISODE_PATH.format(uuid=episode_uuid), json=payload, tool_name="st memory update",
    )
    if not result.get("success"):
        typer.echo(f"Error updating episode: {result}")
        raise typer.Exit(1)
    typer.echo(f"Updated: {episode_uuid[:8]}")
    if tier is not None:
        typer.echo(f"  Tier: {tier}")


def _echo_patched_props(
    props: dict[str, object], summary: str | None, trigger_types: str | None,
    trigger_phases: str | None, pinned: bool | None, context_kind: str | None,
    applicability: dict[str, list[str]] | None, render_mode: str | None = None,
) -> None:
    if summary is not None:
        typer.echo(f"  Summary: {summary}")
    if trigger_types is not None:
        typer.echo(f"  Trigger types: {props['trigger_task_types']}")
    if trigger_phases is not None:
        typer.echo(f"  Trigger phases: {props['trigger_phases']}")
    if pinned is not None:
        typer.echo(f"  Pinned: {pinned}")
    if context_kind is not None:
        typer.echo(f"  Context kind: {props['context_kind']}")
    if render_mode is not None:
        typer.echo(f"  Render mode: {props.get('render_mode') or 'auto'}")
    if applicability is not None:
        typer.echo(f"  Applicability: {applicability}")


def patch_episode_properties(
    target_uuid: str, summary: str | None, trigger_types: str | None,
    trigger_phases: str | None, pinned: bool | None, context_kind: str | None,
    applicability: dict[str, list[str]] | None, *, change_reason: str | None = None,
    render_mode: str | None = None,
) -> None:
    """Patch episode properties and echo results.

    `render_mode` values: None = leave unchanged, RENDER_MODE_CLEAR sentinel =
    clear (send null to API), or one of 'full' / 'compact' / 'summary'.
    """
    props: dict[str, object] = {}
    if summary is not None:
        props["summary"] = summary
    if trigger_types is not None:
        props["trigger_task_types"] = parse_csv_values(trigger_types) or []
    if trigger_phases is not None:
        props["trigger_phases"] = parse_csv_values(trigger_phases) or []
    if pinned is not None:
        props["pinned"] = pinned
    if context_kind is not None:
        props["context_kind"] = validate_context_kind(context_kind)
    if render_mode is not None:
        # Caller already passed validated render_mode (or RENDER_MODE_CLEAR).
        props["render_mode"] = None if render_mode == RENDER_MODE_CLEAR else render_mode
    if applicability is not None:
        props["applicability"] = applicability
    if change_reason:
        props["change_reason"] = change_reason
    patch_result = agent_hub_request(
        "PATCH", MEMORY_EPISODE_PROPERTIES_PATH.format(uuid=target_uuid), json=props, tool_name="st memory update",
    )
    if not patch_result.get("success"):
        typer.echo(f"Warning: Failed to update properties: {patch_result.get('message', 'Unknown')}")
        return
    _echo_patched_props(props, summary, trigger_types, trigger_phases, pinned, context_kind, applicability, render_mode)


def replace_episode_tags(target_uuid: str, tags: list[str]) -> None:
    """Replace tags on an episode."""
    result = agent_hub_request(
        "PUT", MEMORY_EPISODE_TAGS_PATH.format(uuid=target_uuid), json={"tags": tags}, tool_name="st memory update",
    )
    if result.get("tags") != tags:
        typer.echo(f"Warning: Failed to update tags on {target_uuid[:8]}")
        return
    typer.echo(f"  Tags: {', '.join(tags) if tags else '(cleared)'}")


def _validate_update_and_normalize(
    content: str | None, tier: str | None, summary: str | None, tags: str | None,
    clear_tags: bool, clear_applicability: bool, trigger_types: str | None,
    trigger_phases: str | None, pinned: bool | None, context_kind: str | None,
    consumer_profiles: str | None, exclude_consumer_profiles: str | None,
    agent_slugs: str | None, exclude_agent_slugs: str | None,
    audience_tags: str | None, exclude_audience_tags: str | None,
    render_mode: str | None = None,
    scope: str | None = None,
) -> tuple[str | None, str | None, list[str] | None, str | None]:
    if tags and clear_tags:
        typer.echo("Error: Specify only one of --tags or --clear-tags")
        raise typer.Exit(1)
    _nullable = (content, tier, summary, trigger_types, trigger_phases, pinned, context_kind,
                 consumer_profiles, exclude_consumer_profiles, agent_slugs, exclude_agent_slugs,
                 audience_tags, exclude_audience_tags, tags, render_mode, scope)
    if not any(f is not None for f in _nullable) and not clear_applicability and not clear_tags:
        typer.echo(
            "Error: Must specify at least one of: --content, --tier, --summary, --trigger-types,"
            " --trigger-phases, --pinned, --context-kind, --render-mode, applicability options,"
            " --tags, --clear-tags, --clear-applicability"
        )
        raise typer.Exit(1)
    if content is not None:
        validate_episode_content_present(content)
    return (
        validate_summary_input(summary, required=False) if summary is not None else None,
        validate_tier(tier) if tier is not None else None,
        [] if clear_tags else parse_tags_csv(tags),
        validate_render_mode_input(render_mode, allow_clear=True),
    )
