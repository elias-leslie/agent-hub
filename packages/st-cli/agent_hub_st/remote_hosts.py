"""Owner commands for remote hosts and their tool credential map, under the agents namespace."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from st_sdk.output import output_error, output_json
from st_sdk.usage import usage

app = typer.Typer(help="Remote hosts: register, revoke, grant tools, and the per-tool credential map")


def _run_local(action: str, **arguments: Any) -> dict[str, Any]:
    # Bind the installed owner backend (or this source checkout), never cwd. No HTTP owner bypass.
    roots = (Path(__file__).resolve().parents[3] / "backend", Path(sys.prefix).resolve().parent)
    root = next((root for root in roots if (root / "app/cli/remote_hosts.py").is_file()), None)
    if root is None:
        raise RuntimeError("Agent Hub local backend is unavailable")
    sys.path.insert(0, str(root))
    from app.cli.remote_hosts import run_remote_host_operation

    return run_remote_host_operation(action, **arguments)


def _emit(action: str, **arguments: Any) -> None:
    try:
        result = _run_local(action, **arguments)
    except ValueError as exc:
        # Storage errors are fixed text and never carry a token or value.
        output_error(str(exc) if type(exc).__module__.startswith("app.") else "Remote host operation refused")
        raise typer.Exit(1) from None
    except Exception:
        output_error("Remote host operation failed; no values displayed")
        raise typer.Exit(1) from None
    output_json(result)


@app.command("list")
@usage(surface="st.agents.hosts.list", cmd="st agents hosts list", when="list remote hosts, their granted tools and when each last fetched", on_demand="agent administration")
def list_cmd() -> None:
    """Every registered host, including revoked ones."""
    _emit("list")


@app.command("add")
@usage(surface="st.agents.hosts.add", cmd="st agents hosts add NAME --token-out FILE", when="register a remote host; its bearer token is written once to a new 0600 file, never printed", on_demand="agent administration")
def add(
    name: Annotated[str, typer.Argument(help="Host name, e.g. the ssh alias")],
    token_out: Annotated[Path, typer.Option("--token-out", help="New file to receive the token (created 0600)")],
) -> None:
    """Register a host, or re-admit a revoked one with a fresh token and no grants.

    Hand the file to the host with `ssh HOST agent-hub install --token-stdin < FILE`, then delete it.
    """
    _emit("add", name=name, token_out=token_out)


@app.command("revoke")
@usage(surface="st.agents.hosts.revoke", cmd="st agents hosts revoke NAME", when="stop every future credential fetch by a host", on_demand="agent administration")
def revoke(name: Annotated[str, typer.Argument()]) -> None:
    """Invalidate the host's token and drop its grants."""
    _emit("revoke", name=name)


@app.command("grant")
@usage(surface="st.agents.hosts.grant", cmd="st agents hosts grant NAME TOOL", when="let a host fetch a tool's served credentials at launch", on_demand="agent administration")
def grant(name: Annotated[str, typer.Argument()], tool: Annotated[str, typer.Argument(help="Tether tool slug")]) -> None:
    _emit("grant", name=name, tool=tool)


@app.command("deny")
@usage(surface="st.agents.hosts.deny", cmd="st agents hosts deny NAME TOOL", when="remove a host's grant for a tool", on_demand="agent administration")
def deny(name: Annotated[str, typer.Argument()], tool: Annotated[str, typer.Argument(help="Tether tool slug")]) -> None:
    _emit("deny", name=name, tool=tool)


@app.command("tools")
@usage(surface="st.agents.hosts.tools", cmd="st agents hosts tools", when="show the per-tool credential map and whether Agent Hub holds each served value (never the values)", on_demand="agent administration")
def tools() -> None:
    """Map rows with stored/expiry state."""
    _emit("tools")


@app.command("tool-add")
@usage(surface="st.agents.hosts.tool-add", cmd="st agents hosts tool-add --tool SLUG --name NAME --command CMD --config-dir ~/DIR (--env-var VAR | --auth-file FILE) [--rotates]", when="add a credential row to the per-tool map", on_demand="agent administration")
def tool_add(
    tool: Annotated[str, typer.Option("--tool", help="Tether tool slug")],
    name: Annotated[str, typer.Option("--name")],
    command: Annotated[str, typer.Option("--command", help="Executable the host shim stands in for")],
    config_dir: Annotated[str, typer.Option("--config-dir", help="The tool's real config dir, ~/-relative")],
    env_var: Annotated[str | None, typer.Option("--env-var")] = None,
    auth_file: Annotated[str | None, typer.Option("--auth-file", help="Path under the config dir")] = None,
    rotates: Annotated[bool, typer.Option("--rotates/--no-rotates")] = False,
    description: Annotated[str, typer.Option("--description")] = "",
) -> None:
    _emit("tool-add", tool_slug=tool, name=name, command=command, config_dir=config_dir,
          env_var=env_var, auth_file=auth_file, rotates=rotates, description=description)


@app.command("tool-remove")
@usage(surface="st.agents.hosts.tool-remove", cmd="st agents hosts tool-remove TOOL NAME", when="remove a map row and any value stored for it", on_demand="agent administration")
def tool_remove(tool: Annotated[str, typer.Argument()], name: Annotated[str, typer.Argument()]) -> None:
    _emit("tool-remove", tool_slug=tool, name=name)


@app.command("credential-set")
@usage(surface="st.agents.hosts.credential-set", cmd="st agents hosts credential-set TOOL NAME [--input FILE|-] [--expires-at ISO]", when="store a non-rotating tool credential created on the workstation; hidden prompt in a terminal, piped stdin or a private file, never argv", on_demand="agent administration")
def credential_set(
    tool: Annotated[str, typer.Argument()],
    name: Annotated[str, typer.Argument()],
    input_file: Annotated[
        str, typer.Option("--input", help="Your private (0600) file, or - (default): piped stdin, or a hidden prompt in a terminal")
    ] = "-",
    expires_at: Annotated[str | None, typer.Option("--expires-at", help="ISO time with timezone")] = None,
) -> None:
    """Save (or replace) the value granted hosts fetch for TOOL/NAME. Hosts push theirs with `agent-hub credential push`."""
    _emit("credential-set", tool_slug=tool, name=name, input_file=input_file, expires_at=expires_at)
