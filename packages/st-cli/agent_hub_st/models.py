"""Model catalog CLI backed by Agent Hub."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from st_sdk.output import output_json
from st_sdk.usage import usage

from ._api_paths import MODELS_BASE_PATH
from .agents_formatters import print_table
from .memory_api import agent_hub_request

app = typer.Typer(help="Agent Hub model catalog")


def _models_api() -> dict[str, Any]:
    return agent_hub_request("GET", MODELS_BASE_PATH, tool_name="st models")


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
