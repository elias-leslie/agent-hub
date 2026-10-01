"""Local Agent Hub owner operations; collector credentials cannot promote sessions."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from st_sdk.output import output_error, output_json
from st_sdk.usage import usage

app = typer.Typer(help="Inspect and operate Agent Hub-owned native session authority")


def _backend_root() -> Path:
    # The trusted executable is installed in the owner's backend environment.
    candidates = (Path(sys.prefix).resolve().parent, Path("/srv/workspaces/projects/agent-hub/backend"), Path("/app"))
    for root in candidates:
        if (root / "app/services/session_ingestion/native_operator.py").is_file():
            return root.resolve()
    raise RuntimeError("The Agent Hub owner backend is unavailable")


def _run_owner_action(action: str, **arguments: Any) -> dict[str, Any]:
    root = _backend_root()
    sys.path.insert(0, str(root))
    from app.services.session_ingestion.native_operator import run_native_operator
    return asyncio.run(run_native_operator(action, owner_root=root, **arguments))


def _emit(action: str, **arguments: Any) -> None:
    try:
        output_json(_run_owner_action(action, **arguments))
    except (ValueError, RuntimeError) as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    except Exception:
        # DB driver errors may embed bound observation payloads or credentials.
        output_error("Native owner operation failed; transaction rolled back")
        raise typer.Exit(1) from None


@app.command("status")
@usage(surface="st.native-sessions.status", cmd="st native-sessions status THREAD", when="inspect durable native capture and promotion eligibility without contacting Codex", task_types=("agent-admin", "incident"))
def status(thread: str) -> None:
    """Read the content-free native capture and promotion state."""
    _emit("status", session_id=thread)


@app.command("acceptance")
@usage(surface="st.native-sessions.acceptance", cmd="st native-sessions acceptance THREAD --canary-receipt FILE --identity-receipt FILE --gate-receipt FILE", when="verify retained runtime evidence and the current canonical ST acceptance gate before promotion", task_types=("agent-admin", "release"))
def acceptance(thread: str, canary_receipt: Annotated[Path, typer.Option("--canary-receipt", exists=True, dir_okay=False)], identity_receipt: Annotated[Path, typer.Option("--identity-receipt", exists=True, dir_okay=False)], gate_receipt: Annotated[Path, typer.Option("--gate-receipt", exists=True, dir_okay=False)]) -> None:
    """Record verified server acceptance; this does not activate projection."""
    _emit("acceptance", session_id=thread, canary_receipt=canary_receipt.resolve(), identity_receipt=identity_receipt.resolve(), gate_receipt=gate_receipt.resolve())


@app.command("projection")
@usage(surface="st.native-sessions.projection", cmd="st native-sessions projection THREAD --mode canonical_managed|shadow", when="activate an accepted managed source or immediately roll back to rollout recovery", task_types=("agent-admin", "incident", "release"))
def projection(thread: str, mode: Annotated[str, typer.Option("--mode")]) -> None:
    """Activate server-accepted managed projection or roll back in one step."""
    if mode not in {"canonical_managed", "shadow"}:
        raise typer.BadParameter("Choose canonical_managed or shadow", param_hint="--mode")
    _emit("projection", session_id=thread, mode=mode)


@app.command("prune-raw")
@usage(surface="st.native-sessions.prune-raw", cmd="st native-sessions prune-raw --project PROJECT --older-than ISO --limit N [--apply]", when="apply an explicit owner retention cutoff while preserving pending, unresolved and conflict evidence", task_types=("agent-admin", "maintenance"))
def prune_raw(project: Annotated[str, typer.Option("--project")], older_than: Annotated[str, typer.Option("--older-than")], limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100, apply: Annotated[bool, typer.Option("--apply")] = False) -> None:
    """Preview or apply an explicit raw-evidence retention cutoff; no default TTL."""
    _emit("prune_raw", project_id=project, older_than=older_than, limit=limit, apply=apply)
