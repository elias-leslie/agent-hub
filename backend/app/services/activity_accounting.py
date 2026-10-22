"""Content-free summaries of retained usage and sampled tool transcript text."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

# These fields are added by Hub/native projection, rather than sent as tool arguments.
_PROJECTION_FIELDS = {
    "call_id", "wrapper_candidate_call_id", "wrapper_correlation", "native_tool_hints",
    "nested_exec_commands", "native_turn_id", "ordering", "source",
}


def number(value: Any) -> int:
    # PostgreSQL SUM(bigint) is NUMERIC, returned as Decimal by asyncpg.
    # Keep exact integer ledger sums instead of silently presenting zero usage.
    if isinstance(value, Decimal) and value.is_finite() and value >= 0 and value == value.to_integral_value():
        return int(value)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def argument_characters(event: Any) -> int:
    data = event.tool_input
    if not isinstance(data, dict) or event.event_type != "tool_use":
        return 0
    arguments = {key: value for key, value in data.items() if key not in _PROJECTION_FIELDS}
    # Opaque custom calls retain their original text in raw, without JSON framing.
    if arguments.get("format") == "opaque" and isinstance(arguments.get("raw"), str):
        return len(arguments["raw"])
    return len(json.dumps(arguments, ensure_ascii=False, separators=(",", ":")))


def transcript_view(rows: list[dict]) -> dict:
    categories = ("substantive", "administration", "unknown")
    total = sum(row["argument_characters"] + row["returned_characters"] for row in rows)
    counts = dict.fromkeys(categories, 0)
    for row in rows:
        category = row["category"]
        coarse = "administration" if category == "necessary_support" else category if category in categories else "unknown"
        counts[coarse] += row["argument_characters"] + row["returned_characters"]
    return {
        "characters": total,
        "argument_characters": sum(row["argument_characters"] for row in rows),
        "returned_characters": sum(row["returned_characters"] for row in rows),
        "calls_with_returned_text": sum(row["has_returned_text"] for row in rows),
        "calls_missing_returned_text": sum(not row["has_returned_text"] for row in rows),
        "breakdown": [{"category": category, "characters": counts[category], "share": counts[category] / total if total else None} for category in categories],
    }


def usage_partitions(row: Any) -> dict:
    """The query normalizes input to include disjoint cache reads/writes."""
    result = {field: number(getattr(row, field, None)) for field in (
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    )}
    detailed = all(isinstance(getattr(row, field, None), (int, Decimal)) for field in ("cache_read_tokens", "cache_write_tokens"))
    result["cache_detail_input_tokens"] = result["input_tokens"] if detailed else 0
    return result
