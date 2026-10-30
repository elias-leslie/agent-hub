"""Agent Hub's local credential commands under the existing agents namespace."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from st_sdk.output import output_error, output_json
from st_sdk.usage import usage

app = typer.Typer(help="Authorized local lab enrollment, refresh, refs and trusted handoff")


def _run_local(action: str, **arguments: Any) -> dict[str, Any]:
    # Bind the installed owner backend (or this source checkout), never cwd or
    # an arbitrary worker-selected module path. No HTTP/loopback owner bypass.
    roots = (Path(__file__).resolve().parents[3] / "backend", Path(sys.prefix).resolve().parent)
    root = next((root for root in roots if (root / "app/cli/lab_credentials.py").is_file()), None)
    if root is None:
        raise RuntimeError("Agent Hub local credential backend is unavailable")
    sys.path.insert(0, str(root))
    from app.cli.lab_credentials import run_lab_operation

    return run_lab_operation(action, **arguments)


def _emit(action: str, **arguments: Any) -> None:
    try:
        result = _run_local(action, **arguments)
    except Exception:
        # Input, crypto, DB and child-launch exceptions can contain sensitive
        # contents. Never render exception text, traceback or local variables.
        output_error("Local lab credential operation failed; no values displayed")
        raise typer.Exit(1) from None
    output_json(result)
    if action == "run":
        raise typer.Exit(result["exit_code"])


@app.command("enroll")
@usage(surface="st.agents.credentials.enroll", cmd="st agents credentials enroll --target TARGET --actor ACTOR --kind synthetic|temporary --input FILE|- [--expires-at ISO]", when="enroll approved lab fields; agents may enroll synthetic actors under existing local lab authority; private file or piped stdin only", on_demand="agent administration")
def enroll(
    target: Annotated[str, typer.Option("--target")],
    actor: Annotated[str, typer.Option("--actor")],
    kind: Annotated[str, typer.Option("--kind")],
    input_file: Annotated[str, typer.Option("--input", help="Current-user-owned private JSON file, or - for piped stdin")],
    expires_at: Annotated[str | None, typer.Option("--expires-at")] = None,
) -> None:
    """Insert an authorized lab actor once; use refresh for known synthetic actors."""
    _emit("enroll", target=target, actor=actor, kind=kind,
          input_file=None if input_file == "-" else Path(input_file), expires_at=expires_at)


@app.command("refresh")
@usage(surface="st.agents.credentials.refresh", cmd="st agents credentials refresh --target TARGET --actor ACTOR --input FILE|- [--expires-at ISO]", when="replace a known synthetic bundle under existing lab authority after local credential or session renewal; never pass values in arguments", on_demand="agent administration")
def refresh(
    target: Annotated[str, typer.Option("--target")],
    actor: Annotated[str, typer.Option("--actor")],
    input_file: Annotated[str, typer.Option("--input", help="Current-user-owned private JSON file, or - for piped stdin")],
    expires_at: Annotated[str | None, typer.Option("--expires-at")] = None,
) -> None:
    """Replace an existing synthetic bundle in full; never reset a target account."""
    _emit("refresh", target=target, actor=actor,
          input_file=None if input_file == "-" else Path(input_file), expires_at=expires_at)


@app.command("refs")
@usage(surface="st.agents.credentials.refs", cmd="st agents credentials refs [--target TARGET]", when="list lab target/actor references (all targets without --target) without reading encrypted values", on_demand="agent administration")
def refs(target: Annotated[str | None, typer.Option("--target", help="One target; omit for every saved target")] = None) -> None:
    """List identity metadata only; presence does not establish validity."""
    _emit("refs", target=target)


@app.command("run", context_settings={"allow_interspersed_args": False})
@usage(surface="st.agents.credentials.run", cmd="st agents credentials run --target TARGET --request FILE -- /absolute/trusted-child [ARGS]", when="trusted local launcher supplies selected lab fields in an inherited descriptor; API tokens do not establish browser sessions", on_demand="agent administration")
def run(
    target: Annotated[str, typer.Option("--target")],
    request_file: Annotated[Path, typer.Option("--request")],
    command: Annotated[list[str], typer.Argument(help="Absolute trusted child executable and nonsecret arguments")],
) -> None:
    """Launch one trusted local adapter with selected fields; suppress its output.

    Read JSON through EOF from the descriptor in AGENT_HUB_LAB_CREDENTIAL_FD:
    {schema_version: 1, target: TARGET, credentials: [{reference: REF, values: FIELDS}]}.
    Only PATH and the descriptor number reach the child's environment. Close the
    descriptor after reading. A trusted login adapter may drive an isolated browser;
    an API token does not establish its browser session. Never use a shell, model
    harness or general browser executable as the recipient.
    """
    _emit("run", target=target, request_file=request_file, command=command)
