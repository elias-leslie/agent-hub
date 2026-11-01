"""Model catalog CLI backed by Agent Hub."""

from __future__ import annotations

import subprocess
import sys
from typing import Annotated, Any

import typer
from st_sdk.output import output_json
from st_sdk.usage import usage

from ._api_paths import (
    MODELS_BASE_PATH,
    MODELS_LAUNCH_DEFAULTS_PATH,
    MODELS_SELECT_PATH,
    MODELS_SELECTION_POLICY_PATH,
)
from .agents_formatters import print_table
from .memory_api import agent_hub_request

app = typer.Typer(help="Agent Hub model catalog, routing advice and managed local downloads")


def _models_api() -> dict[str, Any]:
    return agent_hub_request("GET", MODELS_BASE_PATH, tool_name="st models")


def _selection_policy_api() -> dict[str, Any]:
    return agent_hub_request("GET", MODELS_SELECTION_POLICY_PATH, tool_name="st models route")


def _launch_api(role: str | None, tool: str | None) -> dict[str, Any]:
    params = {key: value for key, value in (("role", role), ("tool", tool)) if value}
    return agent_hub_request("GET", MODELS_LAUNCH_DEFAULTS_PATH, params=params or None, tool_name="st models route")


def _select_api(task: str) -> dict[str, Any]:
    # Advisory mode only: the service reports whether automatic use would qualify.
    return agent_hub_request(
        "POST", MODELS_SELECT_PATH, json={"task_type": task, "mode": "advisory"},
        tool_name="st models route",
    )


def _score(model: dict[str, Any], key: str) -> str:
    scores = model.get("scores")
    if not isinstance(scores, dict):
        return "-"
    value = scores.get(key)
    return str(value) if value is not None else "-"


def _cost(model: dict[str, Any], key: str) -> str:
    cost = model.get("cost")
    if not isinstance(cost, dict):
        return "-"
    value = cost.get(key)
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value)


def _caps(model: dict[str, Any]) -> dict[str, Any]:
    caps = model.get("capabilities")
    return caps if isinstance(caps, dict) else {}


def _matches_filters(
    model: dict[str, Any],
    *,
    ids: list[str],
    provider: str | None,
    free: bool,
    coding: bool,
) -> bool:
    if ids and str(model.get("id")) not in ids and str(model.get("alias")) not in ids:
        return False
    if provider and str(model.get("provider")) != provider:
        return False
    if free and "free" not in str(model.get("availability") or "").lower():
        return False
    return not (coding and not _caps(model).get("supports_tool_execution"))


def _print_models(models: list[dict[str, Any]], total: int) -> None:
    print(f"MODELS[{len(models)} shown/{total} total]")
    rows: list[list[str]] = []
    for model in models:
        caps = _caps(model)
        rows.append([
            str(model.get("id") or "-"),
            str(model.get("provider") or "-"),
            _score(model, "coding"),
            _score(model, "tool_use"),
            _score(model, "reasoning"),
            f"{_cost(model, 'input_per_m')}/{_cost(model, 'output_per_m')}",
            str(model.get("speed_tier") or "-"),
            "yes" if caps.get("supports_tool_execution") else "no",
            str(model.get("availability") or "-"),
        ])
    print_table(["id", "provider", "C", "T", "R", "$/M in/out", "speed", "tools", "availability"], rows)


def _list_models(
    *,
    model_id: Annotated[list[str] | None, typer.Option("--id", help="Filter by model id or alias.")] = None,
    provider: Annotated[str | None, typer.Option("--provider", help="Filter by provider.")] = None,
    free: Annotated[bool, typer.Option("--free", help="Only models marked free/free-tier.")] = False,
    coding: Annotated[bool, typer.Option("--coding", help="Only tool-capable coding candidates.")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 50,
    as_json: Annotated[bool, typer.Option("--json", help="Print filtered payload as JSON.")] = False,
) -> None:
    payload = _models_api()
    raw_models = payload.get("models") if isinstance(payload, dict) else None
    all_models = [m for m in raw_models if isinstance(m, dict)] if isinstance(raw_models, list) else []
    ids = [str(item) for item in (model_id or [])]
    filtered = [
        model
        for model in all_models
        if _matches_filters(model, ids=ids, provider=provider, free=free, coding=coding)
    ]
    shown = filtered[:limit]
    if as_json:
        output_json({**payload, "models": shown, "total": len(filtered)})
        return
    _print_models(shown, len(filtered))


@app.callback(invoke_without_command=True)
def models_default(
    ctx: typer.Context,
    model_id: Annotated[list[str] | None, typer.Option("--id", help="Filter by model id or alias.")] = None,
    provider: Annotated[str | None, typer.Option("--provider", help="Filter by provider.")] = None,
    free: Annotated[bool, typer.Option("--free", help="Only models marked free/free-tier.")] = False,
    coding: Annotated[bool, typer.Option("--coding", help="Only tool-capable coding candidates.")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 50,
    as_json: Annotated[bool, typer.Option("--json", help="Print filtered payload as JSON.")] = False,
) -> None:
    """List canonical model catalog entries."""
    if ctx.invoked_subcommand is None:
        _list_models(
            model_id=model_id,
            provider=provider,
            free=free,
            coding=coding,
            limit=limit,
            as_json=as_json,
        )


@app.command("list")
@usage(
    surface="st.models",
    cmd="st models [list] [--id MODEL] [--provider PROVIDER] [--free] [--coding] --limit N",
    when="inspect canonical Agent Hub model catalog without raw DB queries",
    task_types=("model-admin", "prompt-tuning", "model-review",),
    on_demand="model administration",
    tier="reference",
)
def list_models(
    model_id: Annotated[list[str] | None, typer.Option("--id", help="Filter by model id or alias.")] = None,
    provider: Annotated[str | None, typer.Option("--provider", help="Filter by provider.")] = None,
    free: Annotated[bool, typer.Option("--free", help="Only models marked free/free-tier.")] = False,
    coding: Annotated[bool, typer.Option("--coding", help="Only tool-capable coding candidates.")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 50,
    as_json: Annotated[bool, typer.Option("--json", help="Print filtered payload as JSON.")] = False,
) -> None:
    """List canonical model catalog entries."""
    _list_models(
        model_id=model_id,
        provider=provider,
        free=free,
        coding=coding,
        limit=limit,
        as_json=as_json,
    )


def _print_task_types(policy: dict[str, Any]) -> None:
    task_types = [str(item) for item in policy.get("task_types") or []]
    print(f"TASK_TYPES[{len(task_types)}] policy=v{policy.get('version', '-')}")
    print("  " + ("  ".join(task_types) if task_types else "-"))


def _effort(row: dict[str, Any]) -> str:
    text = f"{row.get('model') or '-'} {row.get('effort') or '-'}"
    return text + (" daybreak" if row.get("daybreak") else "")


def _daybreak(row: dict) -> str:
    """on, off (a Codex row that sets it off) or - (the tool has no Daybreak)."""
    return {True: "on", False: "off"}.get(row.get("daybreak"), "-")


def _print_launch(payload: dict[str, Any]) -> None:
    raw = payload.get("rows")
    rows = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    if len(rows) == 1:
        row = rows[0]
        rank = f"{row['rank']}/{len(row.get('prefer') or [])}" if row.get("rank") else "not listed"
        print(f"LAUNCH[{payload.get('role')} {row.get('tool')}] job={row.get('job')} ({row.get('label')}) "
              f"policy=v{payload.get('version', '-')}")
        state = "" if row.get("use") and row.get("launchable") else " (not used: no default applies)"
        print(f"  model={row.get('model') or '-'} effort={row.get('effort') or '-'} "
              f"daybreak={_daybreak(row)} "
              f"context={row.get('context')}{state}")
        print(f"  tool order={' > '.join(row.get('prefer') or []) or '-'} (this tool: {rank})")
        for alt in row.get("alternates") or []:
            if isinstance(alt, dict):
                print(f"  instead: {_effort(alt)} when {alt.get('when') or '-'}")
        if row.get("subagent"):
            print(f"  native subagent: {row['subagent']}")
        print(f"  why={row.get('why') or '-'}")
        return
    print(f"LAUNCH[{len(rows)} rows] policy=v{payload.get('version', '-')} "
          "(st models route --role JOB --tool TOOL for one row with its reasons)")
    print_table(["job", "tool", "model", "effort", "daybreak", "context", "rank", "subagent"], [
        [
            str(row.get("job")), str(row.get("tool")),
            str(row.get("model") or ("-" if row.get("use") else "not used")),
            str(row.get("effort") or "-"), _daybreak(row), str(row.get("context")),
            str(row.get("rank") or "-"), str(row.get("subagent") or "-"),
        ]
        for row in rows
    ])


def _print_route(advice: dict[str, Any]) -> None:
    effort = advice.get("effort_details")
    effort = effort if isinstance(effort, dict) else {}
    provenance = advice.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    health = advice.get("catalog_health")
    health = health if isinstance(health, dict) else {}
    print(
        f"ROUTE[{advice.get('task_type', '-')}] policy=v{provenance.get('policy_version', '-')} "
        f"mode={advice.get('mode', '-')}"
    )
    target = f"model={advice.get('model', '-')} effort={advice.get('effort', '-')}"
    if not advice.get("available"):
        target = f"none available; first candidate {target}"
    effective = effort.get("effective") or "unmapped"
    print(f"  {target} effective={effective} ({effort.get('basis') or '-'})")
    if provenance.get("rationale"):
        print(f"  why={provenance['rationale']}")
    qualified = "qualified" if advice.get("automatic_eligible") else "not qualified"
    print(f"  automatic={qualified}: {advice.get('automatic_reason') or '-'}")
    stale = health.get("is_stale")
    state = "unknown" if stale is None else ("stale" if stale else "fresh")
    print(f"  catalog={state} last_sync={str(health.get('last_sync') or '-')[:10]}")
    raw = advice.get("candidates_checked")
    checked = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    print(f"CANDIDATES[{len(checked)} checked]")
    print_table(["model", "effort", "available", "reasons"], [
        [
            str(item.get("model") or "-"),
            str(item.get("effort") or "-"),
            "yes" if item.get("available") else "no",
            "; ".join(str(reason) for reason in item.get("reasons") or []) or "-",
        ]
        for item in checked
    ])


@app.command("route")
@usage(
    surface="st.models.route",
    cmd="st models route [--role JOB --tool TOOL | --task TASK] [--json]",
    when="which model, effort, Daybreak and context an agent gets for a job (--role, a work role or job such as testing or lookup) and tool; st aico create applies it by default. --task: completion-route advice; no options lists both",
    task_types=("model-admin", "model-review"),
    on_demand="model administration",
    tier="reference",
)
def route_model(
    role: Annotated[str | None, typer.Option("--role", help="Launch table: a work role or job (testing, lookup).")] = None,
    tool: Annotated[str | None, typer.Option("--tool", help="Launch table: claude-code, codex, pi, agent-hub or antigravity.")] = None,
    task: Annotated[str | None, typer.Option("--task", help="Completion-route task type; omit to list task types.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the API response as JSON.")] = False,
) -> None:
    """Model, effort, Daybreak and context by job and tool; --task gives completion-route advice."""
    if task and (role or tool):
        raise typer.BadParameter("--task is completion-route advice; use it without --role/--tool")
    if role or tool:
        payload = _launch_api(role, tool)
    elif task:
        payload = _select_api(task)
    else:
        payload = {"task_types": _selection_policy_api(), "launch": _launch_api(None, None)}
    if as_json:
        output_json(payload)
    elif role or tool:
        _print_launch(payload)
    elif task:
        _print_route(payload)
    else:
        _print_task_types(payload["task_types"])
        _print_launch(payload["launch"])


@app.command("pull")
@usage(
    surface="st.models.pull",
    cmd="st models pull MODEL",
    when="download a public model while the local Ollama daemon stays offline",
    precautions=("Uses managed resource admission and a temporary loopback registry. Refuses to replace an existing different manifest; requires the official ollama CLI and a running local daemon.",),
    task_types=("model-admin",),
    on_demand="model administration",
    tier="reference",
)
def pull_model(model: Annotated[str, typer.Argument(help="Public Ollama [namespace/]name[:tag].")]) -> None:
    """Download through an ephemeral registry; preserve the native model manifest."""
    from .model_download_registry import model_name

    try:
        model_name(model)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    # Keep ST's import environment separate; this interpreter has the owner wheel.
    result = subprocess.run(
        ["st", "tools", "run", "--label", f"Download Ollama model {model}", "--",
         sys.executable, "-m", "agent_hub_st.model_download", model],
        check=False,
    )
    raise typer.Exit(result.returncode)
