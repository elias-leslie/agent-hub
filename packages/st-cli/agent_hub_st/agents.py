"""Agent management CLI for Agent Hub-backed settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from st_sdk.output import output_error, output_json
from st_sdk.usage import usage

from .agents_api import agent_preview_api, agents_api, models_api
from .agents_formatters import (
    print_agent_activity,
    print_agent_detail,
    print_agent_versions,
    print_agents_by_model,
    print_compact_agents,
    score_map,
)
from .agents_memory import collect_memory_flags, resolve_memory_config
from .agents_payload import build_agent_payload
from .agents_routing import sync_manual_route
from .preview_formatters import print_preview_detail, print_preview_summary

app = typer.Typer(help="Agent management (Agent Hub)")


def _load_json_file(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        output_error(f"{label} file not found: {path}")
        raise typer.Exit(1)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        output_error(f"Invalid JSON in {label} file: {exc}")
        raise typer.Exit(1) from exc
    if not isinstance(data, dict):
        output_error(f"{label} file must contain a JSON object")
        raise typer.Exit(1)
    return data


def _load_text_file(path: Path, label: str) -> str:
    if not path.exists():
        output_error(f"{label} file not found: {path}")
        raise typer.Exit(1)
    return path.read_text(encoding="utf-8")


def _print_agent(agent: dict[str, Any]) -> None:
    print_agent_detail(agent)


def _score_map() -> dict[str, dict[str, Any]]:
    return score_map(models_api())


def _print_compact_agents(result: dict[str, Any], *, with_scores: bool) -> None:
    print_compact_agents(result, with_scores=with_scores, scores_by_model=_score_map())


def _print_agents_by_model(result: dict[str, Any]) -> None:
    print_agents_by_model(result, scores_by_model=_score_map())


def _sync_manual_route(
    slug: str,
    *,
    primary_model: str | None,
    fallback_model: list[str] | None,
    escalation_model: str | None,
    routing_mode: str | None,
    change_reason: str | None,
) -> None:
    sync_manual_route(
        slug,
        primary_model=primary_model,
        fallback_model=fallback_model,
        escalation_model=escalation_model,
        routing_mode=routing_mode,
        change_reason=change_reason,
        agents_api=agents_api,
        output_error=output_error,
    )


@app.callback(invoke_without_command=True)
def agents_default(ctx: typer.Context) -> None:
    """List agents by default."""
    if ctx.invoked_subcommand is None:
        list_agents()


@app.command("list")
def list_agents(
    active_only: Annotated[bool, typer.Option("--active-only/--all")] = True,
    coding_only: Annotated[bool | None, typer.Option("--coding-only/--non-coding")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    as_json: Annotated[bool, typer.Option("--json", help="Print full API payload.")] = False,
    scores: Annotated[bool, typer.Option("--scores", help="Show compact assignment rows with all score dimensions.")] = False,
    by_model: Annotated[bool, typer.Option("--by-model", help="Group active agents by primary model.")] = False,
) -> None:
    """List agents."""
    params: dict[str, Any] = {
        "active_only": str(active_only).lower(),
        "limit": limit,
        "offset": offset,
    }
    if coding_only is not None:
        params["is_coding_agent"] = str(coding_only).lower()
    result = agents_api("GET", "", params=params)
    if as_json:
        output_json(result)
        return
    if by_model:
        _print_agents_by_model(result)
        return
    _print_compact_agents(result, with_scores=scores)


@app.command("get")
@usage(
    surface="st.agents.get",
    cmd="st agents get <slug> [--json]",
    when="inspect one agent's canonical routing, fallbacks, escalation, timeout, and memory summary",
    task_types=("agent-admin", "prompt-tuning",),
    on_demand="agent administration",
    tier="reference",
)
def get_agent(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
    as_json: Annotated[bool, typer.Option("--json", help="Print full API payload.")] = False,
) -> None:
    """Get one agent by slug."""
    agent = agents_api("GET", f"/{slug}")
    if as_json:
        output_json(agent)
        return
    _print_agent(agent)


@app.command("versions")
@usage(
    surface="st.agents.versions",
    cmd="st agents versions <slug> --limit N",
    when="inspect compact agent routing/config version history without raw DB queries",
    task_types=("agent-admin", "prompt-tuning",),
    on_demand="agent administration",
    tier="reference",
)
def agent_versions(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 20,
    as_json: Annotated[bool, typer.Option("--json", help="Print full API payload.")] = False,
) -> None:
    """Show compact agent version history."""
    result = agents_api("GET", f"/{slug}/versions", params={"limit": limit})
    if as_json:
        output_json(result)
        return
    versions = [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []
    print_agent_versions(versions)


@app.command("activity")
@usage(
    surface="st.agents.activity",
    cmd="st agents activity <slug> [--external-id TASK] --limit N",
    when="inspect recent agent sessions and complete requests without raw DB queries",
    task_types=("agent-admin", "prompt-tuning",),
    on_demand="agent administration",
    tier="reference",
)
def agent_activity(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
    external_id: Annotated[str | None, typer.Option("--external-id", help="Filter by caller external/task id.")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    as_json: Annotated[bool, typer.Option("--json", help="Print full API payload.")] = False,
) -> None:
    """Show recent agent sessions and request logs."""
    params: dict[str, Any] = {"limit": limit}
    if external_id:
        params["external_id"] = external_id
    result = agents_api("GET", f"/{slug}/activity", params=params)
    if as_json:
        output_json(result)
        return
    print_agent_activity(result)


@app.command("create")
def create_agent(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
    name: Annotated[str, typer.Argument(help="Display name")],
    primary_model: Annotated[str, typer.Option("--primary-model", help="Primary model id.")],
    system_prompt_file: Annotated[Path, typer.Option("--system-prompt-file", help="System prompt file.")],
    description: Annotated[str | None, typer.Option("--description")] = None,
    temperature: Annotated[float, typer.Option("--temperature", min=0.0, max=2.0)] = 0.1,
    timeout_seconds: Annotated[float | None, typer.Option("--timeout-seconds", min=1.0)] = None,
    thinking_level: Annotated[str | None, typer.Option("--thinking-level")] = None,
    verbosity_level: Annotated[str | None, typer.Option("--verbosity-level")] = None,
    active: Annotated[bool, typer.Option("--active/--inactive")] = True,
    coding_agent: Annotated[bool, typer.Option("--coding-agent/--non-coding-agent")] = False,
    fallback_model: Annotated[list[str] | None, typer.Option("--fallback-model")] = None,
    escalation_model: Annotated[str | None, typer.Option("--escalation-model")] = None,
    memory_config_file: Annotated[Path | None, typer.Option("--memory-config-file")] = None,
) -> None:
    """Create an agent using the Agent Hub API."""
    payload: dict[str, Any] = {
        "slug": slug,
        "name": name,
        "system_prompt": _load_text_file(system_prompt_file, "System prompt"),
        "primary_model_id": primary_model,
        "temperature": temperature,
        "is_active": active,
        "is_coding_agent": coding_agent,
    }
    for key, val in [
        ("description", description),
        ("thinking_level", thinking_level),
        ("verbosity_level", verbosity_level),
        ("fallback_models", fallback_model),
        ("escalation_model_id", escalation_model),
        ("timeout_seconds", timeout_seconds),
    ]:
        if val is not None:
            payload[key] = val
    if memory_config_file is not None:
        payload["memory_config"] = _load_json_file(memory_config_file, "Memory config")
    _print_agent(agents_api("POST", "", json=payload))


@app.command("preview")
@usage(
    surface="st.agents.preview",
    cmd="st agents preview <slug> --json",
    when="inspect agent prompt/context size; verify injection",
    task_types=("agent-admin", "prompt-tuning",),
    on_demand="agent administration",
    tier="reference",
)
def preview_agent(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
    mode: Annotated[str, typer.Option("--mode", "-m", help="Preview mode: chat, heartbeat, wake, review")] = "chat",
    project: Annotated[str | None, typer.Option("--project", "-P", help="Optional project scope")] = None,
    phase: Annotated[str | None, typer.Option("--phase", help="Optional phase/event hint")] = None,
    prompt_input: Annotated[str | None, typer.Option("--input", help="Optional task input placeholder")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print raw JSON response")] = False,
    full_context_only: Annotated[bool, typer.Option("--full-context-only", help="Print only the effective full context")] = False,
    show_content: Annotated[bool, typer.Option("--show-content", help="Print full section bodies plus full context.")] = False,
) -> None:
    """Show the effective runtime prompt/context preview for an agent."""
    preview = agent_preview_api(
        slug, task_type=mode, project_id=project, phase=phase, prompt_input=prompt_input,
    )
    if as_json:
        output_json(preview)
        return

    full_context = preview.get("full_context") or preview.get("combined_prompt") or ""
    if full_context_only:
        print(full_context)
        return

    if show_content:
        print_preview_detail(preview, mode, project, phase, full_context)
        return

    print_preview_summary(preview, mode, project, phase)


@app.command("update")
def update_agent(
    slug: Annotated[str, typer.Argument(help="Agent slug")],
    name: Annotated[str | None, typer.Option("--name")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    primary_model: Annotated[str | None, typer.Option("--primary-model")] = None,
    escalation_model: Annotated[str | None, typer.Option("--escalation-model")] = None,
    routing_mode: Annotated[str | None, typer.Option("--routing-mode")] = None,
    temperature: Annotated[float | None, typer.Option("--temperature", min=0.0, max=2.0)] = None,
    timeout_seconds: Annotated[float | None, typer.Option("--timeout-seconds", min=1.0)] = None,
    thinking_level: Annotated[str | None, typer.Option("--thinking-level")] = None,
    active: Annotated[bool | None, typer.Option("--active/--inactive")] = None,
    coding_agent: Annotated[bool | None, typer.Option("--coding-agent/--non-coding-agent")] = None,
    fallback_model: Annotated[list[str] | None, typer.Option("--fallback-model")] = None,
    clear_fallback_models: Annotated[bool, typer.Option("--clear-fallback-models")] = False,
    system_prompt_file: Annotated[Path | None, typer.Option("--system-prompt-file")] = None,
    memory_config_file: Annotated[Path | None, typer.Option("--memory-config-file")] = None,
    clear_memory_config: Annotated[bool, typer.Option("--clear-memory-config")] = False,
    memory_enabled: Annotated[bool | None, typer.Option("--memory-enabled/--memory-disabled")] = None,
    include_mandates: Annotated[bool | None, typer.Option("--include-mandates/--no-include-mandates")] = None,
    include_guardrails: Annotated[bool | None, typer.Option("--include-guardrails/--no-include-guardrails")] = None,
    include_references: Annotated[bool | None, typer.Option("--include-references/--no-include-references")] = None,
    continuity_enabled: Annotated[bool | None, typer.Option("--continuity-enabled/--no-continuity-enabled")] = None,
    continuity_max_sessions: Annotated[int | None, typer.Option("--continuity-max-sessions", min=1, max=20)] = None,
    audience_tags: Annotated[str | None, typer.Option("--audience-tags")] = None,
    add_audience_tags: Annotated[str | None, typer.Option("--add-audience-tags")] = None,
    remove_audience_tags: Annotated[str | None, typer.Option("--remove-audience-tags")] = None,
    clear_audience_tags: Annotated[bool, typer.Option("--clear-audience-tags")] = False,
    exclude_tags: Annotated[str | None, typer.Option("--exclude-tags")] = None,
    add_exclude_tags: Annotated[str | None, typer.Option("--add-exclude-tags")] = None,
    remove_exclude_tags: Annotated[str | None, typer.Option("--remove-exclude-tags")] = None,
    clear_exclude_tags: Annotated[bool, typer.Option("--clear-exclude-tags")] = False,
    change_reason: Annotated[str | None, typer.Option("--change-reason")] = None,
) -> None:
    """Update an agent using the Agent Hub API."""
    if clear_fallback_models and fallback_model is not None:
        output_error("Use either --fallback-model or --clear-fallback-models, not both.")
        raise typer.Exit(1)
    effective_fallback_model = [] if clear_fallback_models else fallback_model
    payload = build_agent_payload(
        name=name, description=description, primary_model=primary_model, temperature=temperature, timeout_seconds=timeout_seconds,
        escalation_model=escalation_model, thinking_level=thinking_level, active=active, coding_agent=coding_agent,
        fallback_model=effective_fallback_model, change_reason=change_reason, system_prompt_file=system_prompt_file,
        load_text_file=_load_text_file,
    )
    mem = collect_memory_flags(
        memory_enabled=memory_enabled, include_mandates=include_mandates,
        include_guardrails=include_guardrails, include_references=include_references,
        continuity_enabled=continuity_enabled, continuity_max_sessions=continuity_max_sessions,
        audience_tags=audience_tags, add_audience_tags=add_audience_tags,
        remove_audience_tags=remove_audience_tags, clear_audience_tags=clear_audience_tags,
        exclude_tags=exclude_tags, add_exclude_tags=add_exclude_tags, remove_exclude_tags=remove_exclude_tags, clear_exclude_tags=clear_exclude_tags,
    )
    memory_result = resolve_memory_config(
        slug,
        mem,
        memory_config_file,
        clear_memory_config,
        agents_api=agents_api,
        load_json_file=_load_json_file,
        output_error=output_error,
    )
    if memory_result is not False:
        payload["memory_config"] = memory_result
    has_routing_update = any([primary_model, effective_fallback_model is not None, escalation_model, routing_mode])
    if not payload and not has_routing_update:
        output_error("Nothing to update. Provide at least one update flag.")
        raise typer.Exit(1)
    updated = agents_api("PUT", f"/{slug}", json=payload) if payload else agents_api("GET", f"/{slug}")
    _sync_manual_route(
        slug,
        primary_model=primary_model,
        fallback_model=effective_fallback_model,
        escalation_model=escalation_model,
        routing_mode=routing_mode,
        change_reason=change_reason,
    )
    _print_agent(updated)
