"""CLI wrapper for the shared web research tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.cli.web_benchmark import benchmark_web
from app.services.tools._executor_web import fetch_web_page, research_web, search_web


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
        choices=("auto", "direct", "jina"),
        default="auto",
        help="Page fetch backend",
    )
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
        choices=("auto", "direct", "jina"),
        default="auto",
        help="Page fetch backend",
    )
    _add_output_options(fetch_parser)

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
        )
    if args.command == "fetch":
        url = _resolve_required_arg(args.url, args.url_arg, "--url")
        return await fetch_web_page(
            url=url,
            max_chars=args.max_chars,
            focus_query=args.focus_query,
            backend=args.backend,
        )
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
