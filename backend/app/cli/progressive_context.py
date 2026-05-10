"""CLI wrapper for centralized progressive-context delivery."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from app.api.memory_agent_handlers import build_progressive_context_response
from app.services.memory.context_resilience import MemoryFailureDetails
from app.services.memory.failure_reporting import MemoryFailureReport, report_memory_failure
from app.services.memory.service import MemoryScope


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch Agent Hub progressive context through the shared in-process path.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="Render formatted progressive context.")
    fetch_parser.add_argument("query_arg", nargs="?", help="Query text")
    fetch_parser.add_argument("--query", help="Query text")
    fetch_parser.add_argument("--project", help="Project ID for project-scoped context")
    fetch_parser.add_argument("--task-type", help="Optional task type")
    fetch_parser.add_argument("--session-id", help="Optional session ID")
    fetch_parser.add_argument("--external-id", help="Optional external/task ID")
    fetch_parser.add_argument("--branch", help="Optional current branch")
    fetch_parser.add_argument("--consumer-profile", help="Optional consumer profile")
    fetch_parser.add_argument("--provider", help="Optional provider label for failure reporting")
    fetch_parser.add_argument("--model", help="Optional model label for failure reporting")
    fetch_parser.add_argument("--session-type", help="Optional session type for failure reporting")
    fetch_parser.add_argument("--cwd", help="Optional cwd for failure reporting")
    fetch_parser.add_argument("--repo-root", help="Optional repo root for failure reporting")
    fetch_parser.add_argument("--debug", action="store_true", help="Include debug block before output")

    status_parser = subparsers.add_parser("status", help="Run a memory context status probe.")
    status_parser.add_argument("--project", help="Project ID for project-scoped probe")
    status_parser.add_argument("--branch", help="Optional current branch for the probe")
    status_parser.add_argument("--consumer-profile", default="agent_startup", help="Consumer profile to test")
    status_parser.add_argument("--query", default="memory status probe", help="Probe query")
    status_parser.add_argument("--json", action="store_true", help="Emit raw JSON")

    report_parser = subparsers.add_parser(
        "report-failure",
        help="Persist a memory failure notice to the shared journal and session timeline.",
    )
    report_parser.add_argument("--operation", required=True, help="Failed operation name")
    report_parser.add_argument("--attempts", type=int, default=0, help="Attempt count")
    report_parser.add_argument("--error-type", required=True, help="Failure type label")
    report_parser.add_argument("--error-message", required=True, help="Failure message")
    report_parser.add_argument("--latency-ms", type=int, default=0, help="Observed latency")
    report_parser.add_argument("--project", help="Project ID")
    report_parser.add_argument("--session-id", help="Optional session ID")
    report_parser.add_argument("--external-id", help="Optional external/task ID")
    report_parser.add_argument("--branch", help="Optional current branch")
    report_parser.add_argument("--consumer-profile", help="Optional consumer profile")
    report_parser.add_argument("--provider", help="Optional provider label")
    report_parser.add_argument("--model", help="Optional model label")
    report_parser.add_argument("--session-type", help="Optional session type")
    report_parser.add_argument("--cwd", help="Optional cwd")
    report_parser.add_argument("--repo-root", help="Optional repo root")
    report_parser.add_argument("--source", default="progressive_context_cli", help="Reporter source label")
    report_parser.add_argument("--json", action="store_true", help="Emit raw JSON")

    return parser


def _resolve_query(explicit: str | None, positional: str | None) -> str:
    if explicit:
        return explicit.strip()
    if positional:
        return positional.strip()
    return sys.stdin.read().strip()


def _render_debug_block(response: Any) -> str:
    debug = response.debug or {}
    mandates = debug.get("mandates", [])
    guardrails = debug.get("guardrails", [])
    reference = debug.get("reference", [])
    stats = debug.get("stats", {})
    lines = [
        "<memory-debug>",
        f"Query: {debug.get('query', '')}",
        (
            f"Tokens: {stats.get('total_tokens', 0)} "
            f"(M:{stats.get('mandates_tokens', 0)} "
            f"G:{stats.get('guardrails_tokens', 0)} "
            f"R:{stats.get('reference_tokens', 0)})"
        ),
        "",
    ]
    if mandates:
        lines.append("MANDATES:")
        lines.extend(
            f"  [{item.get('id', '')}] score={item.get('score', 0)}: {item.get('snippet', '')}"
            for item in mandates
        )
    if guardrails:
        lines.append("GUARDRAILS:")
        lines.extend(
            f"  [{item.get('id', '')}] score={item.get('score', 0)}: {item.get('snippet', '')}"
            for item in guardrails
        )
    if reference:
        lines.append("REFERENCE:")
        lines.extend(
            f"  [{item.get('id', '')}] score={item.get('score', 0)}: {item.get('snippet', '')}"
            for item in reference
        )
    if not mandates and not guardrails and not reference:
        lines.append("No memories matched query")
    lines.append("</memory-debug>")
    return "\n".join(lines)


async def _fetch_context(args: argparse.Namespace):
    query = _resolve_query(args.query, args.query_arg)
    if not query:
        return None
    project_id = (args.project or "").strip() or None
    scope = MemoryScope.PROJECT if project_id else MemoryScope.GLOBAL
    return await build_progressive_context_response(
        query=query,
        scope=scope,
        scope_id=project_id,
        debug=args.debug,
        include_global=True,
        task_type=args.task_type,
        external_id=args.external_id,
        project_id=project_id,
        session_id=args.session_id,
        current_branch=args.branch,
        consumer_profile=args.consumer_profile,
    )


async def _fetch_and_maybe_report(args: argparse.Namespace):
    response = await _fetch_context(args)
    if response is None:
        return None
    if response.status != "ok" and response.failure is not None:
        await report_memory_failure(
            _build_failure_report(
                args,
                MemoryFailureDetails(
                    operation=response.failure.operation,
                    attempts=response.failure.attempts,
                    error_type=response.failure.error_type,
                    error_message=response.failure.error_message,
                    latency_ms=response.failure.latency_ms,
                ),
                source="progressive_context_fetch",
            )
        )
    return response


async def _probe_status(args: argparse.Namespace):
    project_id = (args.project or "").strip() or None
    scope = MemoryScope.PROJECT if project_id else MemoryScope.GLOBAL
    response = await build_progressive_context_response(
        query=args.query,
        scope=scope,
        scope_id=project_id,
        debug=False,
        include_global=True,
        task_type=None,
        project_id=project_id,
        current_branch=args.branch,
        consumer_profile=args.consumer_profile,
    )
    payload = {
        "healthy": response.status == "ok",
        "status": response.status,
        "attempts": response.attempts,
        "latency_ms": response.latency_ms,
        "project_id": project_id,
        "scope": scope.value,
        "consumer_profile": args.consumer_profile,
        "failure": response.failure.model_dump() if response.failure else None,
    }
    return payload


def _resolved_cwd(args: argparse.Namespace) -> str | None:
    return (getattr(args, "cwd", None) or os.getcwd()).strip() or None


def _build_failure_report(
    args: argparse.Namespace,
    failure: MemoryFailureDetails,
    *,
    source: str,
) -> MemoryFailureReport:
    return MemoryFailureReport(
        failure=failure,
        consumer_profile=getattr(args, "consumer_profile", None),
        project_id=getattr(args, "project", None),
        session_id=getattr(args, "session_id", None),
        external_id=getattr(args, "external_id", None),
        current_branch=getattr(args, "branch", None),
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        session_type=getattr(args, "session_type", None),
        cwd=_resolved_cwd(args),
        repo_root=getattr(args, "repo_root", None),
        source=source,
    )


async def _report_failure(args: argparse.Namespace) -> dict[str, object]:
    report = _build_failure_report(
        args,
        MemoryFailureDetails(
            operation=args.operation,
            attempts=max(args.attempts, 0),
            error_type=args.error_type,
            error_message=args.error_message,
            latency_ms=max(args.latency_ms, 0),
        ),
        source=args.source,
    )
    result = await report_memory_failure(report)
    return {
        "journal_path": result.journal_path,
        "session_event_recorded": result.session_event_recorded,
        "session_event_error": result.session_event_error,
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "fetch":
        response = asyncio.run(_fetch_and_maybe_report(args))
        if response is None:
            return 0
        if args.debug and response.debug:
            print(_render_debug_block(response))
        if response.formatted:
            print(response.formatted)
        return 0 if response.status == "ok" else 2

    if args.command == "report-failure":
        payload = asyncio.run(_report_failure(args))
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(
                f"journal_path={payload['journal_path']} "
                f"session_event_recorded={payload['session_event_recorded']}"
            )
            if payload["session_event_error"]:
                print(f"session_event_error={payload['session_event_error']}")
        return 0

    payload = asyncio.run(_probe_status(args))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        health_label = "OK" if payload["healthy"] else "FAILED"
        print(
            f"memory={health_label} scope={payload['scope']} "
            f"project={payload['project_id'] or '-'} profile={payload['consumer_profile']} "
            f"attempts={payload['attempts']} latency_ms={payload['latency_ms']}"
        )
        failure = payload.get("failure")
        if failure:
            print(
                f"failure={failure['error_type']} operation={failure['operation']} "
                f"message={failure['error_message']}"
            )
    return 0 if payload["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
