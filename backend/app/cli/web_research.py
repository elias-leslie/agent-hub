"""CLI wrapper for the shared web research tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys

from app.cli.web_benchmark import benchmark_web
from app.services.tools._executor_web import (
    fetch_web_batch,
    fetch_web_page,
    refocus_web_artifact,
    research_web,
    search_web,
)
from app.services.tools._executor_web_lightpanda import doctor_lightpanda

_COVERAGE_HELP = (
    "Coverage: direct content_complete describes the returned extraction view.\n"
    "coverage.source_completeness remains unverified; JavaScript readiness does\n"
    "not prove full source coverage. Verify the returned facts."
)


def _resolve_required_arg(primary: str | None, fallback: str | None, name: str) -> str:
    value = (primary or fallback or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--compact",
        "--raw",
        dest="compact",
        action="store_true",
        help="Emit compact single-line JSON instead of pretty JSON",
    )


def _add_dom_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--selector", help="Lightpanda only: extract the first matching CSS element")
    parser.add_argument("--wait-script", help="Lightpanda only: wait for a predicate on scoped readable content (see example below)")
    parser.add_argument("--timeout", type=float, default=20.0, help="Positive request/process deadline in seconds (default 20)")
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Scoped readiness example:\n"
        "  --backend lightpanda --selector article\n"
        "  --wait-script 'document.querySelector(\"article\")?.innerText.includes(\"Conclusion\")'\n\n"
        "Match expected readable content in the target article or #report.\n"
        "document.body.textContent can include inline scripts and styles, causing\n"
        "a predicate to pass before the readable content is ready. Prefer scoped\n"
        "innerText and verify the returned facts after readiness passes.\n\n"
        + _COVERAGE_HELP
    )


def _dom_options(args: argparse.Namespace) -> dict[str, object]:
    # Keep the existing default call contract intact for callers and dispatch tests.
    return {key: value for key, value in {
        "selector": args.selector, "wait_script": args.wait_script,
        "timeout": args.timeout if args.timeout != 20.0 else None,
    }.items() if value is not None}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run centralized web research using Agent Hub's shared tool stack.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="Search the public web.")
    search_parser.add_argument("query_arg", nargs="?", help="Search query")
    search_parser.add_argument("--query", help="Search query")
    search_parser.add_argument(
        "--max-results",
        "--limit",
        dest="max_results",
        type=int,
        default=5,
        help="Max results to return",
    )
    search_parser.add_argument(
        "--search-type",
        choices=("text", "news"),
        default="text",
        help="Search scope",
    )
    search_parser.add_argument(
        "--timelimit",
        choices=("d", "w", "m", "y"),
        help="Optional search recency filter",
    )
    _add_output_options(search_parser)

    research_parser = subparsers.add_parser(
        "research",
        help="Search first, then fetch one result through the shared web stack.",
    )
    research_parser.add_argument("query_arg", nargs="?", help="Research query")
    research_parser.add_argument("--query", help="Research query")
    research_parser.add_argument(
        "--max-results",
        "--limit",
        dest="max_results",
        type=int,
        default=5,
        help="Max search results to consider",
    )
    research_parser.add_argument("--result-index", type=int, default=1, help="1-based result rank to fetch")
    research_parser.add_argument(
        "--search-type",
        choices=("text", "news"),
        default="text",
        help="Search scope",
    )
    research_parser.add_argument(
        "--timelimit",
        choices=("d", "w", "m", "y"),
        help="Optional search recency filter",
    )
    research_parser.add_argument(
        "--max-chars",
        type=int,
        default=12000,
        help="Maximum fetched content characters to return",
    )
    research_parser.add_argument(
        "--focus-query",
        help="Optional question/topic used to focus the fetched page before truncation",
    )
    research_parser.add_argument(
        "--backend",
        choices=("auto", "direct", "jina", "lightpanda"),
        default="auto",
        help="Page fetch backend",
    )
    _add_dom_options(research_parser)
    _add_output_options(research_parser)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch and extract a webpage.")
    fetch_parser.add_argument("url_arg", nargs="?", help="HTTP or HTTPS URL")
    fetch_parser.add_argument("--url", help="HTTP or HTTPS URL")
    fetch_parser.add_argument(
        "--max-chars",
        type=int,
        default=12000,
        help="Maximum content characters to return",
    )
    fetch_parser.add_argument(
        "--focus-query",
        help="Optional question/topic used to focus large pages before truncation",
    )
    fetch_parser.add_argument(
        "--backend",
        choices=("auto", "direct", "jina", "lightpanda"),
        default="auto",
        help="Page fetch backend",
    )
    _add_dom_options(fetch_parser)
    _add_output_options(fetch_parser)

    batch_parser = subparsers.add_parser("batch", help="Fetch URLs serially, reuse HTTP connections, and retain full artifacts.")
    batch_parser.add_argument("urls", nargs="+", help="HTTP or HTTPS URLs")
    batch_parser.add_argument("--max-chars", type=int, default=12000)
    batch_parser.add_argument("--focus-query")
    batch_parser.add_argument("--backend", choices=("auto", "direct", "jina", "lightpanda"), default="auto")
    _add_dom_options(batch_parser)
    _add_output_options(batch_parser)

    refocus_parser = subparsers.add_parser("refocus", help="Refocus a full extracted artifact in the owner cache without network access.",
        epilog=_COVERAGE_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    refocus_parser.add_argument("artifact_arg", nargs="?", help="Artifact id or absolute owner cache path")
    refocus_parser.add_argument("--artifact", help="Artifact id or absolute owner cache path")
    refocus_parser.add_argument("--max-chars", type=int, default=12000)
    refocus_parser.add_argument("--focus-query")
    _add_output_options(refocus_parser)

    doctor_parser = subparsers.add_parser("doctor", help="Verify the configured Lightpanda binary, exact digest and version (no network).",
        description="Verify the local Lightpanda executable, full SHA256 digest and exact version without network access.")
    doctor_parser.add_argument("--timeout", type=float, default=20.0)
    _add_output_options(doctor_parser)

    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="Run deterministic local web fetch benchmarks.",
    )
    benchmark_parser.add_argument("--iterations", type=int, default=3)
    benchmark_parser.add_argument("--max-chars", type=int, default=800)
    _add_output_options(benchmark_parser)
    return parser


async def _run_command(args: argparse.Namespace) -> str:
    if args.command == "search":
        query = _resolve_required_arg(args.query, args.query_arg, "--query")
        return await search_web(
            query=query,
            max_results=args.max_results,
            search_type=args.search_type,
            timelimit=args.timelimit,
        )
    if args.command == "research":
        query = _resolve_required_arg(args.query, args.query_arg, "--query")
        return await research_web(
            query=query,
            max_results=args.max_results,
            result_index=args.result_index,
            search_type=args.search_type,
            timelimit=args.timelimit,
            max_chars=args.max_chars,
            focus_query=args.focus_query,
            backend=args.backend,
            **_dom_options(args),
        )
    if args.command == "fetch":
        url = _resolve_required_arg(args.url, args.url_arg, "--url")
        return await fetch_web_page(
            url=url,
            max_chars=args.max_chars,
            focus_query=args.focus_query,
            backend=args.backend,
            **_dom_options(args),
        )
    if args.command == "batch":
        return await fetch_web_batch(args.urls, max_chars=args.max_chars, focus_query=args.focus_query,
                                     backend=args.backend, **_dom_options(args))
    if args.command == "refocus":
        artifact = _resolve_required_arg(args.artifact, args.artifact_arg, "--artifact")
        return refocus_web_artifact(artifact, max_chars=args.max_chars, focus_query=args.focus_query)
    if args.command == "doctor":
        if args.timeout <= 0 or not math.isfinite(args.timeout):
            raise ValueError("--timeout must be finite and positive")
        return json.dumps(await doctor_lightpanda(args.timeout))
    if args.command == "benchmark":
        return await benchmark_web(
            iterations=max(1, min(args.iterations, 10)),
            max_chars=max(100, min(args.max_chars, 5000)),
        )
    raise ValueError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--describe-st"]:
        from app.cli.web_extension import describe_extension

        print(json.dumps(describe_extension(), sort_keys=True))
        return 0
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        payload = asyncio.run(_run_command(args))
    except ValueError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        print(payload)
        return 1

    print(json.dumps(parsed, indent=None if args.compact else 2, sort_keys=True))
    if args.command == "benchmark" and parsed.get("passed") is False:
        return 1
    return 0 if "error" not in parsed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
