"""CLI wrapper for the shared web research tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.services.tools._executor_web import fetch_web_page, research_web, search_web


def _resolve_required_arg(primary: str | None, fallback: str | None, name: str) -> str:
    value = (primary or fallback or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


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
        )
    if args.command == "fetch":
        url = _resolve_required_arg(args.url, args.url_arg, "--url")
        return await fetch_web_page(
            url=url,
            max_chars=args.max_chars,
            focus_query=args.focus_query,
        )
    raise ValueError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    payload = asyncio.run(_run_command(args))

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        print(payload)
        return 1

    print(json.dumps(parsed, indent=2, sort_keys=True))
    return 0 if "error" not in parsed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
