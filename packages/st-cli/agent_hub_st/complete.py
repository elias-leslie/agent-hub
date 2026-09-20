"""Complete command - Quick access to Agent Hub /api/complete endpoint."""

from __future__ import annotations

from typing import Annotated, Any

import typer
from st_sdk.usage import usage
from st_sdk.output import output_json

from .completion import call_complete, completion_failed, resolve_message

app = typer.Typer(help="Agent Hub completion API")
_Opt, _Arg = typer.Option, typer.Argument


_resolve_message = resolve_message


def _output_result(result: dict[str, Any], stream: bool, raw: bool) -> None:
    """Output the completion result to stdout."""
    if stream and not raw:
        return
    if raw:
        output_json(result)
    else:
        typer.echo(result.get("content", ""))


_completion_failed = completion_failed


@app.callback(invoke_without_command=True)
@usage(surface="st.complete", cmd="st complete --agent <slug> --file <path>", when="send an authorized completion request through Agent Hub",
       task_types=("agent-admin", "research",), on_demand="completion")
def complete_default(
    ctx: typer.Context,
    message: Annotated[str | None, _Arg(help="Message to send")] = None,
    message_option: Annotated[str | None, _Opt("--message", help="Message to send without relying on positional ordering")] = None,
    agent: Annotated[str | None, _Opt("--agent", "-a", help="Agent slug")] = None,
    model: Annotated[str | None, _Opt("--model", "-M", help="Model override (e.g. cloudflare/qwen2.5-coder-32b). Uses @mention injection to override agent's default model.")] = None,
    project: Annotated[str | None, _Opt("--project", "-p", help="Project ID")] = None,
    source: Annotated[str, _Opt("--source", "-s", help="Source client")] = "st-cli",
    session_id: Annotated[str | None, _Opt("--session", "-S", help="Continue existing session")] = None,
    memory: Annotated[bool, _Opt("--memory/--no-memory", "-m", help="Enable memory injection")] = True,
    memory_group: Annotated[str | None, _Opt("--memory-group", "-g", help="Memory group ID")] = None,
    task_type: Annotated[str | None, _Opt("--task-type", help="Optional task type label (e.g. wake, heartbeat)")] = None,
    thinking_level: Annotated[str | None, _Opt("--thinking", help="Thinking level: minimal|low|medium|high|ultrathink")] = None,
    skip_cache: Annotated[bool, _Opt("--skip-cache", help="Bypass response cache")] = False,
    stream: Annotated[bool, _Opt("--stream", help="Stream response via SSE")] = False,
    trace_id: Annotated[str | None, _Opt("--trace", help="Trace ID for event correlation")] = None,
    include_roles: Annotated[str | None, _Opt("--roles", help="Comma-separated prompt roles to include")] = None,
    image: Annotated[list[str] | None, _Opt("--image", "-i", help="Image file path(s) for multimodal input")] = None,
    audio: Annotated[list[str] | None, _Opt("--audio", "-A", help="Audio file path(s): WAV, MP3, AIFF, AAC, OGG, or FLAC")] = None,
    file: Annotated[str | None, _Opt("--file", "-f", help="Read message from file")] = None,
    timeout: Annotated[float | None, _Opt("--timeout", "-t", help="Optional HTTP read-timeout ceiling in seconds. Omit to wait for completion.")] = None,
    raw: Annotated[bool, _Opt("--raw", help="Output raw JSON")] = False,
) -> None:
    """Send a completion request to Agent Hub.

    Input priority: message argument > --file > piped stdin.

    Examples:
        st complete "Say hello"
        st complete -a critic --file /tmp/review.txt
        st complete -a game-audio-critic --audio /tmp/mix.wav "Review this mix"
        cat prompt.txt | st complete -a reasoner
        st complete -a coder --stream "Write a hello world"
    """
    if ctx.invoked_subcommand is not None:
        return
    resolved_message = _resolve_message(message_option or message, file)
    if not resolved_message:
        typer.echo(ctx.get_help())
        return
    if model:
        resolved_message = f"@{model} {resolved_message}"
    roles = [r.strip() for r in include_roles.split(",")] if include_roles else None
    if not project:
        from st_sdk.config import get_config_optional

        cfg = get_config_optional()
        project = cfg.project_id or "st-cli"
    result = call_complete(
        agent, resolved_message, project, source, memory, memory_group,
        False, None, timeout, skip_cache, session_id,
        thinking_level, 1, stream, trace_id, roles, task_type, image or None,
        audios=audio or None,
    )
    _output_result(result, stream, raw)
    if _completion_failed(result):
        raise typer.Exit(1)
