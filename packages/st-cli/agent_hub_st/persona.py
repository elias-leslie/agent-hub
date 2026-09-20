"""Persona CLI — manage the first-class persona identity."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from st_sdk.usage import usage
from st_sdk.output import output_error, output_json

from .agents_api import agent_preview_api
from .persona_display import (
    get_dispatch_hint as _get_dispatch_hint,
)
from .persona_display import (
    maybe_report_dispatch as _maybe_report_dispatch,
)
from .persona_display import (
    print_heartbeat_result as _print_heartbeat_result,
)
from .persona_display import (
    print_persona as _print_persona,
)
from .persona_helpers import (
    api_call as _api,
)
from .persona_helpers import (
    apply_file_and_scalar_fields as _apply_file_and_scalar_fields,
)
from .persona_helpers import (
    edit_text_in_editor as _edit_text_in_editor,
)
from .persona_helpers import (
    load_limits_field,
    map_hours_to_time_range,
    print_activity_sessions,
    print_update_result,
)
from .persona_helpers import (
    write_file as _write_file,
)
from .preview_formatters import print_preview_detail as _print_preview_detail
from .preview_formatters import print_preview_summary as _print_preview_summary

app = typer.Typer(help="Manage the persona identity")
_Opt = typer.Option
_Arg = typer.Argument

# Re-export for backward compatibility with tests
__all__ = ["_api", "_get_dispatch_hint", "app"]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
@usage(surface="st.persona", cmd="st persona show", when="inspect or manage the Agent Hub persona",
       task_types=("agent-admin",), on_demand="agent administration")
def show() -> None:
    """Show full persona configuration."""
    from .persona_api import get_persona

    _print_persona(_api(get_persona, "Failed to fetch persona"))


@app.command()
def update(
    heartbeat_instructions: Annotated[str | None, _Opt("--heartbeat-instructions", "-H", help="Import heartbeat instructions from file into DB")] = None,
    user_context: Annotated[str | None, _Opt("--user-context", "-U", help="File with user context")] = None,
    voice_enabled: Annotated[bool | None, _Opt("--voice-enabled/--no-voice", help="Toggle voice")] = None,
    voice_id: Annotated[str | None, _Opt("--voice-id", help="Voice ID string")] = None,
    heartbeat_interval: Annotated[int | None, _Opt("--heartbeat-interval", help="Minutes between heartbeats (0-1440)")] = None,
    session_reset_mode: Annotated[str | None, _Opt("--session-reset-mode", help="off, daily, or idle")] = None,
    session_reset_hour: Annotated[int | None, _Opt("--session-reset-hour", help="Hour (0-23) for daily reset")] = None,
    greeting: Annotated[str | None, _Opt("--greeting", help="Greeting message")] = None,
    limits: Annotated[str | None, _Opt("--limits", help="JSON file for limits")] = None,
) -> None:
    """Update persona fields. Text fields accept file paths."""
    from .persona_api import update_persona

    fields: dict[str, Any] = {}
    _apply_file_and_scalar_fields(
        fields, heartbeat_instructions, user_context, voice_enabled, voice_id,
        heartbeat_interval, session_reset_mode, session_reset_hour, greeting,
    )
    if limits is not None:
        load_limits_field(fields, limits)
    if not fields:
        output_error("No fields specified. Use --help to see available flags.")
        raise typer.Exit(1)
    result = _api(lambda: update_persona(fields), "Failed to update persona")
    print_update_result(result, fields)


@app.command()
def personality(
    edit: Annotated[bool, _Opt("--edit", "-e", help="Open $EDITOR to modify personality")] = False,
    set_text: Annotated[str | None, _Opt("--set", "-s", help="Set personality text directly")] = None,
) -> None:
    """Print or modify the personality document."""
    from .persona_api import get_personality, update_personality

    if edit and set_text is not None:
        output_error("--edit and --set are mutually exclusive")
        raise typer.Exit(1)
    if set_text is not None:
        result = _api(
            lambda: update_personality(set_text, reason="Set via st persona personality --set"),
            "Failed to update personality",
        )
        print(f"Personality updated (version {result.get('version', '?')})")
        return
    current = _api(get_personality, "Failed to fetch personality")
    if not edit:
        print(current["personality"] if current.get("personality") else "(No personality document set)")
        return
    new_text = _edit_text_in_editor(current.get("personality") or "")
    if new_text is None:
        print("No changes made.")
        return
    result = _api(
        lambda: update_personality(new_text, reason="Edited via st persona personality --edit"),
        "Failed to update personality",
    )
    print(f"Personality updated (version {result.get('version', '?')})")


@app.command()
def name(
    new_name: Annotated[str | None, _Arg(help="New name for the persona")] = None,
) -> None:
    """Show or set the persona's display name."""
    from .persona_api import get_persona, update_persona

    if new_name is not None:
        result = _api(lambda: update_persona({"name": new_name}), "Failed to update name")
        print(f"Name updated: {result.get('name', new_name)}")
        return
    persona = _api(get_persona, "Failed to fetch persona")
    print(persona.get("name", "Unknown"))


@app.command()
def instructions(
    edit: Annotated[bool, _Opt("--edit", "-e", help="Open $EDITOR to modify")] = False,
    set_text: Annotated[str | None, _Opt("--set", "-s", help="Set heartbeat instructions directly")] = None,
    export: Annotated[str | None, _Opt("--export", help="Export DB-backed heartbeat instructions to file")] = None,
) -> None:
    """Print, modify, or export DB-backed heartbeat instructions."""
    from .persona_api import get_persona, update_persona

    if sum([edit, set_text is not None, export is not None]) > 1:
        output_error("--edit, --set, and --export are mutually exclusive")
        raise typer.Exit(1)
    if set_text is not None:
        result = _api(
            lambda: update_persona({"heartbeat_instructions": set_text}),
            "Failed to update heartbeat instructions",
        )
        print(f"Heartbeat instructions updated (version {result.get('version', '?')})")
        return
    persona = _api(get_persona, "Failed to fetch persona")
    text = persona.get("heartbeat_instructions") or ""
    if export is not None:
        _write_file(export, text)
        print(f"Heartbeat instructions exported to {export} ({len(text)} chars)")
        return
    if edit:
        new_text = _edit_text_in_editor(text)
        if new_text is None:
            print("No changes made.")
            return
        result = _api(
            lambda: update_persona({"heartbeat_instructions": new_text}),
            "Failed to update heartbeat instructions",
        )
        print(f"Heartbeat instructions updated (version {result.get('version', '?')})")
        return
    print(text if text else "(No heartbeat instructions set)")


@app.command()
def preview(
    mode: Annotated[str, _Opt("--mode", "-m", help="Preview mode: chat, heartbeat, wake, review")] = "heartbeat",
    project: Annotated[str | None, _Opt("--project", "-P", help="Optional project scope")] = None,
    phase: Annotated[str | None, _Opt("--phase", help="Optional phase/event hint")] = None,
    prompt_input: Annotated[str | None, _Opt("--input", help="Optional prompt input placeholder")] = None,
    as_json: Annotated[bool, _Opt("--json", help="Print raw JSON response")] = False,
    combined_only: Annotated[bool, _Opt("--combined-only", help="Print only the full combined context")] = False,
    show_content: Annotated[bool, _Opt("--show-content", help="Print full section bodies plus full context.")] = False,
) -> None:
    """Show the effective runtime prompt/context preview for Jenny."""
    preview_data = _api(
        lambda: agent_preview_api(
            "persona",
            task_type=mode,
            project_id=project,
            phase=phase,
            prompt_input=prompt_input,
        ),
        "Failed to fetch persona preview",
    )
    if as_json:
        output_json(preview_data)
        return
    full_context = preview_data.get("full_context") or preview_data.get("combined_prompt") or ""
    if combined_only:
        print(full_context)
        return
    if show_content:
        _print_preview_detail(preview_data, mode, project, phase, full_context)
        return
    _print_preview_summary(preview_data, mode, project, phase)


@app.command()
def heartbeat(
    watch: Annotated[bool, _Opt("--watch", "-w", help="Poll until heartbeat completes")] = False,
    project: Annotated[str | None, _Opt("--project", "-P", help="Target project for this manual heartbeat")] = None,
) -> None:
    """Trigger a heartbeat. With --watch, poll until it finishes."""
    import time

    from ..client import STClient
    from .persona_api import get_heartbeat_status, trigger_heartbeat

    try:
        result = trigger_heartbeat(project)
        print(f"Heartbeat {result.get('status', 'dispatched')}: {result.get('message', '')}")
    except Exception as e:
        _handle_heartbeat_trigger_error(e)

    if not watch:
        return

    pulse_client = STClient(require_project=False) if project else None
    reported_dispatch = False
    print("Watching...", end="", flush=True)
    while True:
        time.sleep(10)
        try:
            hb_status = get_heartbeat_status()
            if not hb_status.get("running"):
                print()
                _print_heartbeat_result(hb_status)
                return
            reported_dispatch = _maybe_report_dispatch(pulse_client, project, reported_dispatch)
            elapsed = hb_status.get("elapsed_seconds", 0)
            print(f"\r  Running... {elapsed}s elapsed", end="", flush=True)
        except Exception:
            print(".", end="", flush=True)


def _handle_heartbeat_trigger_error(e: Exception) -> None:
    """Translate heartbeat trigger HTTP errors to user-friendly messages."""
    status_code = getattr(getattr(e, "response", None), "status_code", None)
    if status_code == 409:
        print("Heartbeat already running")
        return
    if status_code == 400:
        output_error("Onboarding not complete")
        raise typer.Exit(1) from e
    if status_code == 403:
        output_error("Heartbeat permission is off")
        raise typer.Exit(1) from e
    output_error(f"Trigger failed: {e}")
    raise typer.Exit(1) from e


@app.command()
def activity(
    hours: Annotated[int, _Opt("--hours", "-H", help="Lookback hours (default 24)")] = 24,
    limit: Annotated[int, _Opt("--limit", "-n", help="Max sessions to show")] = 10,
) -> None:
    """Show recent persona activity sessions."""
    from .persona_api import get_activity

    time_range = map_hours_to_time_range(hours)
    data = _api(lambda: get_activity(time_range=time_range, page_size=limit), "Failed to fetch activity")
    print_activity_sessions(data.get("sessions", []), data.get("total", 0), time_range)


@app.command()
def status() -> None:
    """Show heartbeat state and persona overview."""
    from .persona_api import get_heartbeat_status, get_persona

    try:
        hb = get_heartbeat_status()
        persona = get_persona()
    except Exception as e:
        output_error(f"Failed to fetch status: {e}")
        raise typer.Exit(1) from e

    running = hb.get("running", False)
    state = "running" if running else "idle"
    last = hb.get("last_run", "never")
    interval = hb.get("interval_minutes", 0)
    elapsed = hb.get("elapsed_seconds")

    elapsed_part = f" ({elapsed}s)" if running and elapsed is not None else ""
    print(f"Heartbeat: {state}{elapsed_part} | Last: {last} | Interval: {interval}m")
    print(f"Persona: {persona.get('name', '?')} | Onboarding: {persona.get('onboarding_phase', '?')}")
