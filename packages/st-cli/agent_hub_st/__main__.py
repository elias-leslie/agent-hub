"""Trusted executable entry point for Agent Hub-owned ST namespaces."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any

import typer
from st_sdk.runtime import run_app

from .agents import app as agents_app
from .complete import app as complete_app
from .feedback import app as feedback_app
from .mandates import mandates
from .memory import app as memory_app
from .models import app as models_app
from .note import note
from .persona import app as persona_app
from .prompt import app as prompt_app
from .skills import app as skills_app


def _leaf_app(name: str, callback: Any) -> typer.Typer:
    app = typer.Typer()
    app.command(name)(callback)
    return app


OWNED_APPS: dict[str, typer.Typer] = {
    "agents": agents_app,
    "complete": complete_app,
    "feedback": feedback_app,
    "mandates": _leaf_app("mandates", mandates),
    "memory": memory_app,
    "models": models_app,
    "note": _leaf_app("note", note),
    "persona": persona_app,
    "prompt": prompt_app,
    "skills": skills_app,
}


def main(args: Sequence[str] | None = None) -> Any:
    """Dispatch the fixed leading namespace to a statically owned Typer app."""
    resolved_args = list(sys.argv[1:] if args is None else args)
    if not resolved_args:
        typer.echo("Missing Agent Hub ST namespace", err=True)
        raise typer.Exit(2)
    namespace, *command_args = resolved_args
    app = OWNED_APPS.get(namespace)
    if app is None:
        typer.echo(f"Unknown Agent Hub ST namespace: {namespace}", err=True)
        raise typer.Exit(2)
    return run_app(app, namespace, command_args)


if __name__ == "__main__":
    main()

