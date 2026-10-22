"""Content-free estimates of tool text added to history, not provider usage."""

from __future__ import annotations

import math

from app.services.activity_accounting import argument_text, number
from app.services.st_activity import POLICY, _encoding

_COUNTS = (
    "admin_tokens_estimate", "other_tokens_estimate", "unknown_tokens_estimate",
    "argument_tokens_estimate", "returned_tokens_estimate", "tools_sampled",
    "tools_missing_output", "tokenized_argument_calls", "estimated_argument_calls",
)


def tool_context_row(tool, result, category: str) -> dict:
    returned = getattr(result, "returned_characters", None)
    return {"category": category if tool.event_type == "tool_use" else "unknown", "arguments": argument_text(tool),
            "returned_characters": number(returned),
            "has_returned_text": isinstance(returned, int) and not isinstance(returned, bool) and returned >= 0,
            "has_arguments": tool.event_type == "tool_use" and isinstance(tool.tool_input, dict)}


def context_split(rows: list[dict], *, truncated: bool = False) -> dict:
    """Use the same per-session tokenizer budget for Activity and Sessions."""
    counts = dict.fromkeys(_COUNTS, 0)
    remaining = POLICY["max_tokenized_characters_per_snapshot"]
    ratio = POLICY["output_characters_per_token"]
    for row in rows:
        text = row["arguments"]
        tokenized = row["has_arguments"] and len(text) <= min(remaining, POLICY["max_tokenized_characters_per_command"])
        arguments = len(_encoding().encode(text, disallowed_special=())) if tokenized else math.ceil(len(text) / ratio)
        if tokenized:
            remaining -= len(text)
        returned = math.ceil(row["returned_characters"] / ratio)
        amount = arguments + returned
        category = row["category"]
        admin = category in {"administration", "necessary_support"}
        unknown = category not in {"administration", "necessary_support", "substantive"}
        counts["admin_tokens_estimate" if admin else "other_tokens_estimate"] += amount
        counts["unknown_tokens_estimate"] += amount if unknown else 0
        counts["argument_tokens_estimate"] += arguments
        counts["returned_tokens_estimate"] += returned
        counts["tools_sampled"] += 1
        counts["tools_missing_output"] += not row["has_returned_text"]
        counts["tokenized_argument_calls"] += tokenized
        counts["estimated_argument_calls"] += row["has_arguments"] and not tokenized
    return combine_context_splits([counts], truncated=truncated)


def combine_context_splits(splits: list[dict], *, truncated: bool = False) -> dict:
    counts = {field: sum(row[field] for row in splits) for field in _COUNTS}
    total = counts["admin_tokens_estimate"] + counts["other_tokens_estimate"]
    return counts | {
        "denominator_tokens_estimate": total,
        "admin_share": counts["admin_tokens_estimate"] / total if total else None,
        "other_share": counts["other_tokens_estimate"] / total if total else None,
        "unknown_share": counts["unknown_tokens_estimate"] / total if total else None,
        "events_truncated": truncated or any(row.get("events_truncated", False) for row in splits),
        "input_token_encoding": POLICY["input_token_encoding"],
        "output_characters_per_token": POLICY["output_characters_per_token"],
    }
