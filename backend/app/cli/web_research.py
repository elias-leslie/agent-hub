"""CLI wrapper for the shared web research tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.services.tools._executor_web import fetch_web_page, search_web


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run centralized web research using Agent Hub's shared tool stack.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="Search the public web.")
    search_parser.add_argument("--query", required=True, help="Search query")
    search_parser.add_argument("--max-results", type=int, default=5, help="Max results to return")
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

    fetch_parser = subparsers.add_parser("fetch", help="Fetch and extract a webpage.")
    fetch_parser.add_argument("--url", required=True, help="HTTP or HTTPS URL")
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
        return await search_web(
            query=args.query,
            max_results=args.max_results,
            search_type=args.search_type,
            timelimit=args.timelimit,
        )
    if args.command == "fetch":
        return await fetch_web_page(
            url=args.url,
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
