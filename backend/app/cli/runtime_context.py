"""CLI wrapper for Agent Hub runtime context rendering."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.db import async_session
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    build_canonical_context_delivery,
    render_runtime_context,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render runtime context for external agentic CLIs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    deliver_parser = subparsers.add_parser(
        "deliver",
        help="Deliver the canonical additive Agent Hub context contract.",
    )
    deliver_parser.add_argument("--surface", required=True, help="Consumer surface name")
    deliver_parser.add_argument(
        "--profile",
        "--consumer-profile",
        dest="consumer_profile",
        default="agent_startup",
    )
    deliver_parser.add_argument("--capability", action="append", default=[])
    deliver_parser.add_argument("--agent-slug", help="Agent Hub agent applicability slug")
    deliver_parser.add_argument(
        "--consumer-tag",
        action="append",
        default=[],
        help="Explicit applicability audience tag; repeatable",
    )
    deliver_parser.add_argument("--project", help="Canonical project ID")
    deliver_parser.add_argument("--session", help="Consumer session ID")
    deliver_parser.add_argument("--task", help="Current task or initial prompt")
    deliver_parser.add_argument("--query", help="Task-aware context selection query")
    deliver_parser.add_argument("--task-type", help="Optional task type")
    deliver_parser.add_argument("--phase", help="Optional lifecycle phase")
    deliver_parser.add_argument("--branch", help="Current git branch")
    deliver_parser.add_argument("--cwd", help="Consumer working directory")
    deliver_parser.add_argument("--repo-root", help="Canonical repository root")
    deliver_parser.add_argument("--provider", help="Consumer provider label")
    deliver_parser.add_argument("--model", help="Consumer model label")
    deliver_parser.add_argument("--variant", help="Optional memory-selection variant")
    deliver_parser.add_argument("--hook-event", help="Native hook event name")
    deliver_parser.add_argument("--source", help="Native launch source")
    deliver_parser.add_argument("--turn-id", help="Native turn ID")
    deliver_parser.add_argument("--subagent-id", help="Native subagent ID")
    deliver_parser.add_argument("--subagent-type", help="Native subagent type")
    deliver_parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional client metadata; repeatable",
    )
    deliver_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output exact rendered text or the full versioned contract",
    )

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


def _parse_metadata(values: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for raw in values:
        key, separator, value = raw.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ValueError(f"Invalid --metadata value {raw!r}; expected KEY=VALUE")
        metadata[key] = value
    return metadata


async def _deliver(args: argparse.Namespace):
    client_metadata = _parse_metadata(args.metadata)
    for key, value in (
        ("hook_event_name", args.hook_event),
        ("source", args.source),
        ("turn_id", args.turn_id),
        ("subagent_id", args.subagent_id),
        ("subagent_type", args.subagent_type),
    ):
        if value:
            client_metadata[key] = value

    request = CanonicalContextDeliveryRequest(
        consumer_surface=args.surface,
        consumer_profile=args.consumer_profile,
        capabilities=args.capability,
        agent_slug=(args.agent_slug or "").strip() or None,
        consumer_tags=args.consumer_tag,
        project_id=(args.project or "").strip() or None,
        session_id=(args.session or "").strip() or None,
        task=args.task,
        query=args.query,
        task_type=args.task_type,
        phase=args.phase,
        current_branch=args.branch,
        cwd=args.cwd,
        repo_root=args.repo_root,
        provider=args.provider,
        model=args.model,
        variant=args.variant,
        client_metadata=client_metadata,
    )
    async with async_session() as db:
        return await build_canonical_context_delivery(db, request)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "deliver":
        try:
            response = asyncio.run(_deliver(args))
        except ValueError as exc:
            parser.error(str(exc))
        if args.format == "json":
            print(json.dumps(response.model_dump(mode="json"), indent=2, sort_keys=True))
        else:
            # stdout bytes exactly match the bytes covered by payload_hash.
            sys.stdout.write(response.rendered)
        return 0 if response.status == "ok" else 2

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
        chunks = [
            response.rendered,
            response.project_index,
            response.continuity,
            response.tool_capabilities,
            response.non_negotiables,
        ]
        print("\n".join(chunk for chunk in chunks if chunk))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
