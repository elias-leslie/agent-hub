"""Drive Agent Hub's durable workflow runner: create, watch, revise and end a multi-step run.

The runner holds all job state; these commands are thin calls to /api/workflow-runs. A coordinator session can end
and later re-attach with ``list --mine``, ``get`` and ``wait``.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, urlsplit

import typer
from st_sdk.config import get_agent_hub_url
from st_sdk.output import output_error, output_json
from st_sdk.usage import usage

from ._api_paths import (
    WORKFLOW_RUN_CANCEL_PATH,
    WORKFLOW_RUN_PATH,
    WORKFLOW_RUN_RESUME_PATH,
    WORKFLOW_RUN_STEP_CANCEL_PATH,
    WORKFLOW_RUN_STEP_PATH,
    WORKFLOW_RUN_STEPS_PATH,
    WORKFLOW_RUNS_PATH,
)
from .memory_api import agent_hub_request
from .workflow_format import list_line, run_text
from .workflow_guide import GUIDE
from .workflow_wait import EXIT_CODES_HELP, parse_until, wait_for

app = typer.Typer(help="Durable multi-model workflow runs (Agent Hub)", no_args_is_help=True)
_Opt, _Arg = typer.Option, typer.Argument

SESSION_ENV = "AICO_SESSION_ID"
AGENT_ENV = "AICO_AGENT_SLUG"
FRONTEND_URL_ENV = "AGENT_HUB_FRONTEND_URL"
FRONTEND_PORT_ENV = "AGENT_HUB_FRONTEND_PORT"
# Host default for the page address, like the host default for the API address: the web app's port on the API's host.
DEFAULT_FRONTEND_PORT = 3003
LIST_FETCH_MAX = 200  # the API's page limit; --mine filters this many recent runs

# Step fields a revision may set, and how --set reads their value.
_TEXT_FIELDS = ("instructions", "agent_slug", "model_override", "executor", "level", "effort")
_REQUIRED_TEXT = ("instructions", "agent_slug")  # the runner refuses to clear these
_LIST_FIELDS = ("allowed_models", "depends_on")
_INT_FIELDS = ("max_attempts",)
_REVISABLE = (*_TEXT_FIELDS, *_LIST_FIELDS, "acceptance", *_INT_FIELDS)

_RunId = Annotated[str, _Arg(help="Workflow run id")]
_AsJson = Annotated[bool, _Opt("--json", help="Print the full API payload.")]


# --- transport and addresses ---------------------------------------------------------------------------------


def _api(method: str, path: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None,
         retries: int = 1) -> dict[str, Any]:
    return agent_hub_request(method, path, params=params, json=payload, tool_name="st workflow", retries=retries)


def page_url(run_id: str) -> str:
    """The run page on the web app: AGENT_HUB_FRONTEND_URL, else the API's scheme and host on the web app's port."""
    base = os.getenv(FRONTEND_URL_ENV, "").strip().rstrip("/")
    if not base:
        parts = urlsplit(get_agent_hub_url())
        port = os.getenv(FRONTEND_PORT_ENV, "").strip() or str(DEFAULT_FRONTEND_PORT)
        host = parts.hostname or "localhost"
        base = f"{parts.scheme or 'http'}://{f'[{host}]' if ':' in host else host}:{port}"
    return f"{base}/workflow-runs/{quote(run_id)}"


def _fail(message: str, code: int = 2) -> typer.Exit:
    output_error(message)
    return typer.Exit(code)


def _read_json(source: str, what: str) -> Any:
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
        return json.loads(text)
    except (OSError, ValueError) as exc:
        raise _fail(f"Cannot read {what} from {source}: {exc}") from None


def _read_object(source: str, what: str) -> dict[str, Any]:
    data = _read_json(source, what)
    if not isinstance(data, dict):
        raise _fail(f"{what} must be a JSON object")
    return data


def _emit(payload: dict[str, Any], as_json: bool, text: str) -> None:
    if as_json:
        output_json(payload)
    else:
        typer.echo(text)


# --- payload building (pure) ---------------------------------------------------------------------------------


def build_create_payload(
    definition: dict[str, Any], *, request_id: str | None = None, max_concurrent_steps: int | None = None,
    tool_level: str | None = None, env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The run definition plus who launched it: launched_by and coordinator come from the Aico session unless set."""
    env = os.environ if env is None else env
    payload = dict(definition)
    for field, name in (("launched_by", SESSION_ENV), ("coordinator", AGENT_ENV)):
        if not payload.get(field) and env.get(name):
            payload[field] = env[name]
    if request_id:
        payload["request_id"] = request_id
    # RunDefinition accepts these settings only inside its policy; any policy in the file is kept.
    for key, value in (("max_concurrent_steps", max_concurrent_steps), ("tool_level", tool_level)):
        if value is not None:
            payload["policy"] = {**(payload.get("policy") or {}), key: value}
    return payload


def _changed_by(env: Mapping[str, str] | None = None) -> str | None:
    return (os.environ if env is None else env).get(SESSION_ENV) or None


def _plan_change(reason: str | None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    change = {"changed_by": _changed_by(env), "reason": reason}
    return {k: v for k, v in change.items() if v}


def build_add_payload(
    data: Any, *, after: str | None = None, reason: str | None = None, env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """One step object, a list of steps, or {"steps": [...]} become the add-steps body."""
    if isinstance(data, list):
        body: dict[str, Any] = {"steps": data}
    elif isinstance(data, dict) and "steps" in data:
        body = dict(data)
    elif isinstance(data, dict):
        body = {"steps": [data]}
    else:
        raise ValueError("step file must be a step object, a list of steps or {steps: [...]}")
    if after:
        body["after"] = after
    for key, value in _plan_change(reason, env).items():
        body.setdefault(key, value)
    return body


def _json_or_text(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def parse_set(pair: str) -> tuple[str, Any]:
    """`field=value` into (field, value). Text stays text; lists take JSON or commas; `null` clears; ints parse."""
    field, sep, raw = pair.partition("=")
    field = field.strip()
    if not sep or field not in _REVISABLE:
        raise ValueError(f"--set {pair!r}: use field=value with field one of {', '.join(_REVISABLE)}")
    if field in _TEXT_FIELDS:
        clearable = field not in _REQUIRED_TEXT
        return field, None if raw == "null" and clearable else raw
    if field in _INT_FIELDS:
        value = _json_or_text(raw)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError(f"--set {field}: expected a whole number or null, got {raw!r}")
        return field, value
    value = _json_or_text(raw)
    if field == "acceptance":
        if isinstance(value, list):
            return field, value
        return field, [raw]
    if value is None:
        return field, None
    if isinstance(value, list):
        return field, value
    return field, [part.strip() for part in raw.split(",") if part.strip()]


def build_revision_payload(
    sets: list[str] | None, file_data: dict[str, Any] | None, *, reason: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = dict(file_data or {})
    for pair in sets or []:
        field, value = parse_set(pair)
        body[field] = value
    if not any(name in body for name in _REVISABLE):
        raise ValueError("nothing to change: pass --set field=value or --file")
    for key, value in _plan_change(reason, env).items():
        body.setdefault(key, value)
    return body


# --- commands ------------------------------------------------------------------------------------------------


@app.callback()
def workflow_group() -> None:
    """Create, watch and steer durable multi-model workflow runs."""


@app.command("guide")
@usage(surface="st.workflow", cmd="st workflow guide", when="before first use of the durable runner: plan, wait, revise, end",
       task_types=("agent-admin", "orchestration"), on_demand="autonomous operations")
def guide() -> None:
    """How a coordinator plans, runs and ends a workflow."""
    typer.echo("\n".join(GUIDE))


@app.command("create")
@usage(surface="st.workflow.create", cmd="st workflow create --file def.json|- [--request-id ID] [--json]",
       when="start a durable run from a step plan; the same --request-id returns the existing run",
       task_types=("agent-admin", "orchestration"), on_demand="autonomous operations")
def create(
    file: Annotated[str, _Opt("--file", "-f", help="Run definition JSON, or - for stdin.")],
    request_id: Annotated[str | None, _Opt("--request-id", help="Stable id: creating again returns the same run.")] = None,
    max_concurrent_steps: Annotated[int | None, _Opt("--max-concurrent-steps", min=1, help="Steps allowed to run at once.")] = None,
    tool_level: Annotated[str | None, _Opt("--tool-level", help="Tools every step gets: read, lean or full.")] = None,
    as_json: _AsJson = False,
) -> None:
    """Create and start a run.

    launched_by and coordinator come from the Aico session unless the file sets them.
    """
    payload = build_create_payload(_read_object(file, "run definition"), request_id=request_id,
                                   max_concurrent_steps=max_concurrent_steps, tool_level=tool_level)
    result = _api("POST", WORKFLOW_RUNS_PATH, payload=payload)
    created = result.get("created", True)
    url = page_url(str(result.get("id")))
    note = "created" if created else f"existing run for request_id {payload.get('request_id')}"
    _emit(result | {"page_url": url}, as_json, f"{note}\n{run_text(result, url)}")


@app.command("get")
@usage(surface="st.workflow.get", cmd="st workflow get RUN [--json]",
       when="see each step's status, requested→served model, attempt n/N, live phase, cost and the run totals",
       task_types=("agent-admin", "orchestration"), on_demand="autonomous operations")
def get(run_id: _RunId, as_json: _AsJson = False) -> None:
    """One line per step, then run totals."""
    view = _api("GET", WORKFLOW_RUN_PATH.format(run_id=run_id), retries=3)
    _emit(view | {"page_url": page_url(run_id)}, as_json, run_text(view, page_url(run_id)))


@app.command("wait", epilog=EXIT_CODES_HELP)
@usage(surface="st.workflow.wait", cmd="st workflow wait RUN [--until done|needs_owner|any-change|step:KEY] [--max-wait SECONDS]",
       when="block until the run ends, pauses for a decision, a step ends or anything changes; prints changes; exit code tells which",
       task_types=("agent-admin", "orchestration"), on_demand="autonomous operations")
def wait(
    run_id: _RunId,
    until: Annotated[str, _Opt("--until", help="done | needs_owner | any-change | step:<key>")] = "done",
    max_wait: Annotated[float | None, _Opt("--max-wait", min=0, help="Seconds, then return exit 30. Cancels nothing; default waits without limit.")] = None,
    poll_min: Annotated[float, _Opt("--poll-min", min=0.5, help="Seconds between reads after a change.")] = 2.0,
    poll_max: Annotated[float, _Opt("--poll-max", min=0.5, help="Seconds between reads once nothing changes.")] = 10.0,
    max_errors: Annotated[int, _Opt("--max-errors", min=1, help="Failed reads in a row before exit 31.")] = 12,
) -> None:
    """Wait for a run to end, pause or change.

    Polls until the condition holds. Stops at a finished run or a pause that needs a decision.
    """
    parse_until(until)
    code = wait_for(
        lambda: _api("GET", WORKFLOW_RUN_PATH.format(run_id=run_id), retries=3), until, emit=typer.echo,
        page_url=page_url(run_id), poll_min=poll_min, poll_max=max(poll_max, poll_min), max_wait=max_wait,
        max_errors=max_errors,
    )
    raise typer.Exit(code)


@app.command("add-step")
@usage(surface="st.workflow.add-step", cmd="st workflow add-step RUN --file step.json|- [--after KEY] [--reason WHY]",
       when="extend the plan with one or more steps, also after the run completed",
       task_types=("agent-admin", "orchestration"), on_demand="autonomous operations")
def add_step(
    run_id: _RunId,
    file: Annotated[str, _Opt("--file", "-f", help="A step object, a list of steps or {steps: [...]}, or - for stdin.")],
    after: Annotated[str | None, _Opt("--after", help="Key of the step the first added step depends on.")] = None,
    reason: Annotated[str | None, _Opt("--reason", help="Why; kept in the plan history.")] = None,
    as_json: _AsJson = False,
) -> None:
    """Add steps to a run."""
    try:
        body = build_add_payload(_read_json(file, "step"), after=after, reason=reason)
    except ValueError as exc:
        raise _fail(str(exc)) from None
    result = _api("POST", WORKFLOW_RUN_STEPS_PATH.format(run_id=run_id), payload=body)
    keys = ", ".join(step["key"] for step in body["steps"] if isinstance(step, dict) and "key" in step)
    _emit(result, as_json, f"added {keys}; plan r{result.get('plan_revision')}; run {result.get('state')}")


@app.command("revise")
@usage(surface="st.workflow.revise", cmd="st workflow revise RUN KEY --set field=value ... | --file revision.json [--reason WHY]",
       when="change a step that has not started: instructions, model, executor, effort, acceptance, max_attempts, depends_on",
       task_types=("agent-admin", "orchestration"), on_demand="autonomous operations")
def revise(
    run_id: _RunId,
    key: Annotated[str, _Arg(help="Step key")],
    set_: Annotated[list[str] | None, _Opt("--set", help="field=value, repeatable. Lists take JSON or commas; null clears.")] = None,
    file: Annotated[str | None, _Opt("--file", "-f", help="Revision JSON object, or - for stdin.")] = None,
    reason: Annotated[str | None, _Opt("--reason", help="Why; kept in the plan history.")] = None,
    as_json: _AsJson = False,
) -> None:
    """Revise a pending step; a step that has started answers 409."""
    try:
        body = build_revision_payload(set_, _read_object(file, "revision") if file else None, reason=reason)
    except ValueError as exc:
        raise _fail(str(exc)) from None
    result = _api("PATCH", WORKFLOW_RUN_STEP_PATH.format(run_id=run_id, key=key), payload=body)
    changed = ", ".join(name for name in body if name in _REVISABLE)
    _emit(result, as_json, f"revised {key} ({changed}); plan r{result.get('plan_revision')}; run {result.get('state')}")


@app.command("remove-step")
@usage(surface="st.workflow.remove-step", cmd="st workflow remove-step RUN KEY [--reason WHY] [--file revise.json]",
       when="drop a pending step nothing else depends on (or revise its dependents in the same call)",
       task_types=("agent-admin", "orchestration"), on_demand="autonomous operations")
def remove_step(
    run_id: _RunId,
    key: Annotated[str, _Arg(help="Step key")],
    reason: Annotated[str | None, _Opt("--reason", help="Why; kept in the plan history.")] = None,
    file: Annotated[str | None, _Opt("--file", "-f", help="JSON {revise: {dependent-key: revision}}, or - for stdin.")] = None,
    as_json: _AsJson = False,
) -> None:
    """Remove a pending step."""
    body = (_read_object(file, "removal") if file else {}) | _plan_change(reason)
    result = _api("DELETE", WORKFLOW_RUN_STEP_PATH.format(run_id=run_id, key=key), payload=body or None)
    _emit(result, as_json, f"removed {key}; plan r{result.get('plan_revision')}; run {result.get('state')}")


@app.command("cancel")
@usage(surface="st.workflow.cancel", cmd="st workflow cancel RUN [--step KEY] [--reason WHY]",
       when="stop the whole run, or one step while the run carries on; work already done is kept",
       task_types=("agent-admin", "orchestration"), on_demand="autonomous operations")
def cancel(
    run_id: _RunId,
    step: Annotated[str | None, _Opt("--step", help="Stop only this step.")] = None,
    reason: Annotated[str | None, _Opt("--reason", help="Why; kept with who asked and when.")] = None,
    as_json: _AsJson = False,
) -> None:
    """Cancel a run or one of its steps. It stops running work; it never deletes history."""
    path = (WORKFLOW_RUN_STEP_CANCEL_PATH.format(run_id=run_id, key=step) if step
            else WORKFLOW_RUN_CANCEL_PATH.format(run_id=run_id))
    result = _api("POST", path, payload={"reason": reason} if reason else None)
    target = f"step {step}" if step else "run"
    stopping = " (stopping running work)" if result.get("cancelling") else ""
    _emit(result, as_json, f"{target} cancel requested; run {result.get('state')}{stopping}")


@app.command("resume")
@usage(surface="st.workflow.resume", cmd="st workflow resume RUN --action retry|skip|fail [--step KEY] [--model M] [--extra-attempts N] [--note TEXT]",
       when="answer a run paused for a decision: retry the step (optionally more attempts or a pinned model), skip it, or fail the run",
       task_types=("agent-admin", "orchestration"), on_demand="autonomous operations")
def resume(
    run_id: _RunId,
    action: Annotated[str, _Opt("--action", help="retry | skip | fail")],
    step: Annotated[str | None, _Opt("--step", help="Step to act on; default is the paused step.")] = None,
    model: Annotated[str | None, _Opt("--model", help="retry: pin this model for the next attempt.")] = None,
    extra_attempts: Annotated[int | None, _Opt("--extra-attempts", min=1, help="retry: attempts to allow past the cap.")] = None,
    note: Annotated[str | None, _Opt("--note", help="Kept with the decision.")] = None,
    as_json: _AsJson = False,
) -> None:
    """Resolve a paused run."""
    if action not in ("retry", "skip", "fail"):
        raise _fail("--action must be retry, skip or fail")
    if extra_attempts is not None and action != "retry":
        raise _fail("--extra-attempts only applies to --action retry")
    body = {"action": action, "step_key": step, "model": model, "note": note, "extra_attempts": extra_attempts}
    result = _api("POST", WORKFLOW_RUN_RESUME_PATH.format(run_id=run_id), payload={k: v for k, v in body.items() if v is not None})
    _emit(result, as_json, f"{action} {result.get('step')}: step {result.get('status')}; run {result.get('state')}")


@app.command("list")
@usage(surface="st.workflow.list", cmd="st workflow list [--mine] [--limit N] [--json]",
       when="find runs, or re-attach to the runs this Aico session launched (--mine)",
       task_types=("agent-admin", "orchestration"), on_demand="autonomous operations")
def list_runs(
    mine: Annotated[bool, _Opt("--mine", help=f"Only runs launched by this session ({SESSION_ENV}).")] = False,
    limit: Annotated[int, _Opt("--limit", min=1, max=LIST_FETCH_MAX)] = 20,
    offset: Annotated[int, _Opt("--offset", min=0)] = 0,
    as_json: _AsJson = False,
) -> None:
    """Recent runs, newest first."""
    session = os.environ.get(SESSION_ENV)
    if mine and not session:
        raise _fail(f"--mine needs {SESSION_ENV}, which is not set in this shell")
    result = _api("GET", WORKFLOW_RUNS_PATH, params={"limit": LIST_FETCH_MAX if mine else limit, "offset": offset}, retries=3)
    rows = [r for r in result.get("runs") or [] if isinstance(r, dict)]
    if mine:
        rows = [r for r in rows if r.get("launched_by") == session][:limit]
    if as_json:
        output_json({**result, "runs": rows})
        return
    for row in rows:
        typer.echo(list_line(row))
    if not rows:
        typer.echo("no runs" + (f" launched by {session}" if mine else ""))
