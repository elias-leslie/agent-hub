"""CLI wrapper for Agent Hub runtime context rendering."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.db import async_session
from app.services.runtime_context import render_runtime_context


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render runtime context for external agentic CLIs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render_parser = subparsers.add_parser("render", help="Render formatted runtime context.")
    render_parser.add_argument("query_arg", nargs="?", help="Selection query")
    render_parser.add_argument("--query", help="Selection query")
    render_parser.add_argument("--consumer-profile", default="agent_startup")
    render_parser.add_argument("--project", help="Optional project ID")
    render_parser.add_argument("--task-type", help="Optional task type")
    render_parser.add_argument("--phase", help="Optional phase")
    render_parser.add_argument("--json", action="store_true", help="Emit full JSON payload")

    status_parser = subparsers.add_parser("status", help="Probe runtime context rendering.")
    status_parser.add_argument("--consumer-profile", default="agent_startup")
    status_parser.add_argument("--project", help="Optional project ID")
    status_parser.add_argument("--query", default="startup context")
    status_parser.add_argument("--json", action="store_true")
    return parser


def _resolve_query(explicit: str | None, positional: str | None) -> str:
    if explicit:
        return explicit.strip()
    if positional:
        return positional.strip()
    return sys.stdin.read().strip() or "startup context"


async def _render(args: argparse.Namespace):
    async with async_session() as db:
        return await render_runtime_context(
            db,
            consumer_profile=args.consumer_profile,
            project_id=(args.project or "").strip() or None,
            query=_resolve_query(getattr(args, "query", None), getattr(args, "query_arg", None)),
            task_type=getattr(args, "task_type", None),
            phase=getattr(args, "phase", None),
        )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    response = asyncio.run(_render(args))
    if getattr(args, "json", False):
        print(json.dumps(response.model_dump(mode="json"), indent=2, sort_keys=True))
    elif args.command == "status":
        print(
            f"runtime_context=OK profile={response.consumer_profile} "
            f"project={response.project_id or '-'} blocks={len(response.blocks)} "
            f"tokens={response.total_tokens}"
        )
    else:
        chunks = [response.project_index, response.tool_capabilities, response.rendered]
        print("\n".join(chunk for chunk in chunks if chunk))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
