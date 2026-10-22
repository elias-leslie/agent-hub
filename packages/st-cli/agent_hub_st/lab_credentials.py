"""Agent Hub's local credential commands under the existing agents namespace."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from st_sdk.output import output_error, output_json
from st_sdk.usage import usage

app = typer.Typer(help="Owner enrollment, metadata refs and trusted local lab handoff")


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
@usage(surface="st.agents.credentials.enroll", cmd="st agents credentials enroll --target TARGET --actor ACTOR --kind synthetic|temporary --input FILE|- [--expires-at ISO]", when="owner enrolls approved lab fields from private file or piped stdin; never pass values in arguments", on_demand="agent administration")
def enroll(
    target: Annotated[str, typer.Option("--target")],
    actor: Annotated[str, typer.Option("--actor")],
    kind: Annotated[str, typer.Option("--kind")],
    input_file: Annotated[str, typer.Option("--input", help="Owner-owned private JSON file, or - for piped stdin")],
    expires_at: Annotated[str | None, typer.Option("--expires-at")] = None,
) -> None:
    """Insert an owner-classified lab actor once; no overwrite or rotation."""
    _emit("enroll", target=target, actor=actor, kind=kind,
          input_file=None if input_file == "-" else Path(input_file), expires_at=expires_at)


@app.command("refs")
@usage(surface="st.agents.credentials.refs", cmd="st agents credentials refs --target TARGET", when="list lab target/actor references without reading encrypted values", on_demand="agent administration")
def refs(target: Annotated[str, typer.Option("--target")]) -> None:
    """List identity metadata only; presence does not establish validity."""
    _emit("refs", target=target)


@app.command("run", context_settings={"allow_interspersed_args": False})
@usage(surface="st.agents.credentials.run", cmd="st agents credentials run --target TARGET --request FILE -- /absolute/trusted-child [ARGS]", when="trusted owner launcher supplies explicitly selected lab fields in an inherited descriptor", on_demand="agent administration")
def run(
    target: Annotated[str, typer.Option("--target")],
    request_file: Annotated[Path, typer.Option("--request")],
    command: Annotated[list[str], typer.Argument(help="Absolute trusted child executable and nonsecret arguments")],
) -> None:
    """Launch one trusted child with selected fields; suppress child output."""
    _emit("run", target=target, request_file=request_file, command=command)
