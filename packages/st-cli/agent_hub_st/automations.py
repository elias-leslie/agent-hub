"""Agent-facing facade for Agent Hub-owned automation profiles and runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from st_sdk.output import output_error, output_json
from st_sdk.usage import usage

from ._api_paths import (
    AUTOMATIONS_POLICY_PATH,
    AUTOMATIONS_PROFILES_PATH,
    AUTOMATIONS_REGISTRY_PATH,
    AUTOMATIONS_RUNS_PATH,
    PROJECT_PERMISSION_PATH,
)
from .memory_api import agent_hub_request

app = typer.Typer(help="Manage canonical Agent Hub background automations")


def _api(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return agent_hub_request(
        method,
        path,
        params=params,
        json=payload,
        tool_name="st automations",
        internal=True,
    )


def _input(path: str) -> dict[str, Any]:
    try:
        content = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
    except (OSError, yaml.YAMLError) as exc:
        output_error(f"Cannot read automation input: {exc}")
        raise typer.Exit(2) from None
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        output_error("Automation input must be a JSON or YAML object with string keys")
        raise typer.Exit(2)
    return parsed


def _emit(payload: dict[str, Any], *, as_json: bool, keys: tuple[str, ...]) -> None:
    if as_json:
        output_json(payload)
        return
    print("|".join(str(payload.get(key) if payload.get(key) is not None else "-") for key in keys))


def _items(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


@app.command("catalog")
@usage(
    surface="st.automations.catalog",
    cmd="st automations catalog [--project PROJECT] [--json]",
    when="discover registered Agent Hub background workflow types before creating a profile",
    task_types=("automation-admin", "agent-admin"),
    on_demand="autonomous operations",
)
def catalog(
    project: Annotated[str | None, typer.Option("--project")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload = _api("GET", AUTOMATIONS_REGISTRY_PATH)
    definitions = _items(payload, "definitions")
    if project:
        definitions = [item for item in definitions if item.get("owner_project_id") == project]
    if as_json:
        output_json({"definitions": definitions})
        return
    for item in definitions:
        _emit(item, as_json=False, keys=("owner_project_id", "workflow_key", "version", "label"))


@app.command("list")
@usage(
    surface="st.automations.list",
    cmd="st automations list [--project PROJECT] [--limit N] [--json]",
    when="inspect effective background automation state and find profile IDs",
    task_types=("automation-admin", "incident", "agent-admin"),
    on_demand="autonomous operations",
)
def list_profiles(
    project: Annotated[str | None, typer.Option("--project")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if project:
        params["project_id"] = project
    payload = _api("GET", AUTOMATIONS_PROFILES_PATH, params=params)
    if as_json:
        output_json(payload)
        return
    for item in _items(payload, "items"):
        _emit(
            item,
            as_json=False,
            keys=("id", "project_id", "workflow_key", "enabled", "effective_enabled", "next_run_at"),
        )
    print(f"TOTAL:{payload.get('total', 0)}")


@app.command("show")
@usage(
    surface="st.automations.show",
    cmd="st automations show PROFILE_ID [--json]",
    when="read one profile and its revision before editing",
    task_types=("automation-admin", "incident"),
    on_demand="autonomous operations",
)
def show(
    profile_id: str,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload = _api("GET", f"{AUTOMATIONS_PROFILES_PATH}/{profile_id}")
    if as_json:
        output_json(payload)
        return
    for key in (
        "id", "project_id", "subject_id", "workflow_key", "revision", "enabled",
        "effective_enabled", "gate_reasons", "schedule_type", "schedule_value",
        "schedule_timezone", "next_run_at", "last_run_at", "config",
    ):
        if key in payload:
            print(f"{key}:{json.dumps(payload[key], ensure_ascii=True, sort_keys=True)}")


@app.command("validate")
@usage(
    surface="st.automations.validate",
    cmd="st automations validate --file PROFILE.json|yaml|- [--json]",
    when="validate an automation profile against its registered workflow contract without saving",
    task_types=("automation-admin",),
    on_demand="autonomous operations",
)
def validate(
    file: Annotated[str, typer.Option("--file", help="JSON/YAML path or - for stdin")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    result = _api("POST", f"{AUTOMATIONS_PROFILES_PATH}/validate", payload=_input(file))
    if as_json:
        output_json(result)
    else:
        print("VALID" if result.get("valid") else "INVALID")
        for issue in result.get("errors") or []:
            print(json.dumps(issue, ensure_ascii=True) if isinstance(issue, dict) else str(issue))
    if not result.get("valid"):
        raise typer.Exit(1)


@app.command("apply")
@usage(
    surface="st.automations.apply",
    cmd="st automations apply --file PROFILE.json|yaml|- [--json]",
    when="create or revise a registered automation profile with revision protection",
    task_types=("automation-admin",),
    on_demand="autonomous operations",
)
def apply(
    file: Annotated[str, typer.Option("--file", help="JSON/YAML path or - for stdin")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload = _input(file)
    profile_id = payload.pop("id", None)
    if profile_id is not None and (not isinstance(profile_id, str) or "expected_revision" not in payload):
        output_error("Updating a profile requires string id and expected_revision")
        raise typer.Exit(2)
    result = _api(
        "PATCH" if profile_id else "POST",
        f"{AUTOMATIONS_PROFILES_PATH}/{profile_id}" if profile_id else AUTOMATIONS_PROFILES_PATH,
        payload=payload,
    )
    _emit(result, as_json=as_json, keys=("id", "revision", "enabled", "effective_enabled"))


@app.command("import")
@usage(
    surface="st.automations.import",
    cmd="st automations import --file OWNER_STATE.json|yaml|- [--json]",
    when="register an owner's existing schedule and cursor without transferring its clock",
    task_types=("automation-admin",),
    on_demand="autonomous operations",
)
def import_owner_state(
    file: Annotated[str, typer.Option("--file", help="JSON/YAML path or - for stdin")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload = _input(file)
    if not isinstance(payload.get("source_ref"), str) or not payload["source_ref"]:
        output_error("Owner import requires a stable source_ref")
        raise typer.Exit(2)
    result = _api("POST", f"{AUTOMATIONS_PROFILES_PATH}/import", payload=payload)
    _emit(result, as_json=as_json, keys=("id", "revision", "clock_owner", "enabled"))


@app.command("cutover")
@usage(
    surface="st.automations.cutover",
    cmd="st automations cutover PROFILE_ID --revision N --fence-receipt RECEIPT [--next-run-at ISO]",
    when="transfer one imported schedule after its owner has durably fenced the old clock",
    task_types=("automation-admin",),
    on_demand="autonomous operations",
)
def cutover(
    profile_id: str,
    revision: Annotated[int, typer.Option("--revision", min=1)],
    fence_receipt: Annotated[str, typer.Option("--fence-receipt")],
    next_run_at: Annotated[str | None, typer.Option("--next-run-at")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if not fence_receipt.strip():
        output_error("Cutover requires a non-empty owner fence receipt")
        raise typer.Exit(2)
    payload: dict[str, Any] = {
        "expected_revision": revision,
        "fence_receipt": fence_receipt,
    }
    if next_run_at:
        payload["next_run_at"] = next_run_at
    result = _api("POST", f"{AUTOMATIONS_PROFILES_PATH}/{profile_id}/cutover", payload=payload)
    _emit(result, as_json=as_json, keys=("id", "revision", "clock_owner", "next_run_at"))


def _set_enabled(profile_id: str, revision: int, enabled: bool, as_json: bool) -> None:
    result = _api(
        "PATCH",
        f"{AUTOMATIONS_PROFILES_PATH}/{profile_id}",
        payload={"enabled": enabled, "expected_revision": revision},
    )
    _emit(result, as_json=as_json, keys=("id", "revision", "enabled", "effective_enabled"))


@app.command("enable")
@usage(
    surface="st.automations.enable",
    cmd="st automations enable PROFILE_ID --revision N",
    when="enable future background runs after inspecting a profile revision",
    task_types=("automation-admin",),
    on_demand="autonomous operations",
)
def enable(
    profile_id: str,
    revision: Annotated[int, typer.Option("--revision", min=1)],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Enable scheduled background admissions for a profile."""
    _set_enabled(profile_id, revision, True, as_json)


@app.command("disable")
@usage(
    surface="st.automations.disable",
    cmd="st automations disable PROFILE_ID --revision N",
    when="stop future background runs without deleting accepted work",
    task_types=("automation-admin", "incident"),
    on_demand="autonomous operations",
)
def disable(
    profile_id: str,
    revision: Annotated[int, typer.Option("--revision", min=1)],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Stop new background admissions for a profile."""
    _set_enabled(profile_id, revision, False, as_json)


@app.command("policy")
@usage(
    surface="st.automations.policy",
    cmd="st automations policy PROJECT_ID [--json]",
    when="inspect shared project automation limits and policy revision",
    task_types=("automation-admin", "incident"),
    on_demand="autonomous operations",
)
def policy(
    project_id: str,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect one project's shared automation policy."""
    result = _api("GET", AUTOMATIONS_POLICY_PATH.format(project_id=project_id))
    if as_json:
        output_json(result)
    else:
        for key in ("project_id", "enabled", "revision", "config"):
            if key in result:
                print(f"{key}:{json.dumps(result[key], ensure_ascii=True, sort_keys=True)}")


@app.command("policy-apply")
@usage(
    surface="st.automations.policy-apply",
    cmd="st automations policy-apply PROJECT_ID --file POLICY.json|yaml|-",
    when="revise project-wide automation limits with an expected revision",
    task_types=("automation-admin",),
    on_demand="autonomous operations",
)
def policy_apply(
    project_id: str,
    file: Annotated[str, typer.Option("--file", help="JSON/YAML path or - for stdin")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Update shared policy using the current revision in the input."""
    payload = _input(file)
    if "expected_revision" not in payload:
        output_error("Policy update requires expected_revision")
        raise typer.Exit(2)
    result = _api("PUT", AUTOMATIONS_POLICY_PATH.format(project_id=project_id), payload=payload)
    _emit(result, as_json=as_json, keys=("project_id", "revision", "enabled"))


@app.command("execution")
@usage(
    surface="st.automations.execution",
    cmd="st automations execution PROJECT_ID [--json]",
    when="inspect the project execution permission gate and hours before changing automated work",
    task_types=("automation-admin", "incident"),
    on_demand="autonomous operations",
)
def execution_permission(
    project_id: str,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Read the execution permission from its existing authorized API."""
    result = _api("GET", PROJECT_PERMISSION_PATH.format(project_id=project_id))
    if as_json:
        output_json(result)
    else:
        for key in (
            "project_id", "permission_tier", "auto_exec_enabled",
            "execution_start_hour", "execution_end_hour",
        ):
            if key in result:
                print(f"{key}:{json.dumps(result[key], ensure_ascii=True, sort_keys=True)}")


@app.command("execution-set")
@usage(
    surface="st.automations.execution-set",
    cmd="st automations execution-set PROJECT_ID [--auto-exec on|off] [--start-hour 0..23 --end-hour 1..24]",
    when="change the project execution permission gate or hours through its existing authorized API",
    task_types=("automation-admin",),
    on_demand="autonomous operations",
)
def execution_permission_set(
    project_id: str,
    auto_exec: Annotated[str | None, typer.Option("--auto-exec")] = None,
    start_hour: Annotated[int | None, typer.Option("--start-hour", min=0, max=23)] = None,
    end_hour: Annotated[int | None, typer.Option("--end-hour", min=1, max=24)] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Update only execution fields; access tier stays in Access Control."""
    if auto_exec not in {None, "on", "off"}:
        output_error("--auto-exec must be on or off")
        raise typer.Exit(2)
    if (start_hour is None) != (end_hour is None):
        output_error("Provide both --start-hour and --end-hour")
        raise typer.Exit(2)
    if start_hour is not None and start_hour == end_hour:
        output_error("Start and end hour cannot be the same")
        raise typer.Exit(2)
    payload: dict[str, Any] = {}
    if auto_exec is not None:
        payload["auto_exec_enabled"] = auto_exec == "on"
    if start_hour is not None:
        payload["execution_start_hour"] = start_hour
        payload["execution_end_hour"] = end_hour
    if not payload:
        output_error("Set --auto-exec or an execution window")
        raise typer.Exit(2)
    result = _api("PATCH", PROJECT_PERMISSION_PATH.format(project_id=project_id), payload=payload)
    _emit(result, as_json=as_json, keys=(
        "project_id", "auto_exec_enabled", "execution_start_hour", "execution_end_hour",
    ))


@app.command("run")
@usage(
    surface="st.automations.run",
    cmd="st automations run PROFILE_ID [--idempotency-key KEY] [--json]",
    when="start an explicit audited cycle under registered manual-run rules",
    task_types=("automation-admin",),
    on_demand="autonomous operations",
)
def run(
    profile_id: str,
    idempotency_key: Annotated[str | None, typer.Option("--idempotency-key")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Start an audited manual cycle under the workflow's registered policy."""
    payload = {"idempotency_key": idempotency_key} if idempotency_key else {}
    result = _api("POST", f"{AUTOMATIONS_PROFILES_PATH}/{profile_id}/run", payload=payload)
    _emit(result, as_json=as_json, keys=("run_id", "status", "admitted", "reason"))


@app.command("runs")
@usage(
    surface="st.automations.runs",
    cmd="st automations runs [--profile ID] [--project PROJECT] [--limit N] [--json]",
    when="inspect background run results and owner receipts",
    task_types=("automation-admin", "incident"),
    on_demand="autonomous operations",
)
def runs(
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    project: Annotated[str | None, typer.Option("--project")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 50,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect accepted, running, failed, and unknown automation runs."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if profile:
        params["profile_id"] = profile
    if project:
        params["project_id"] = project
    result = _api("GET", AUTOMATIONS_RUNS_PATH, params=params)
    if as_json:
        output_json(result)
        return
    for item in _items(result, "items"):
        _emit(item, as_json=False, keys=("id", "profile_id", "status", "scheduled_for", "owner_run_id"))
    print(f"TOTAL:{result.get('total', 0)}")


@app.command("review")
@usage(
    surface="st.automations.review",
    cmd="st automations review PROFILE_ID [--through-run-id RUN_ID]",
    when="record review of an imported or changed automation profile",
    task_types=("automation-admin",),
    on_demand="autonomous operations",
)
def review(
    profile_id: str,
    through_run_id: Annotated[str | None, typer.Option("--through-run-id")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Mark one profile reviewed through its current or selected run."""
    payload = {"through_run_id": through_run_id} if through_run_id else {}
    result = _api("POST", f"{AUTOMATIONS_PROFILES_PATH}/{profile_id}/review", payload=payload)
    _emit(result, as_json=as_json, keys=("id", "revision", "unreviewed_count", "last_reviewed_at"))
