"""Score and price normalization helpers for model enrichment."""

from __future__ import annotations

import re
from typing import Any

# arimxyer benchmark index scale (scores go up to ~57)
_ARIMXYER_INDEX_SCALE = 57.0

# LiveBench task → category mapping
LIVEBENCH_REASONING_TASKS = [
    "zebra_puzzle", "spatial", "connections", "consecutive_events",
    "logic_with_navigation", "theory_of_mind",
]
LIVEBENCH_IF_TASKS = [
    "paraphrase", "story_generation", "summarize", "simplify",
]


def _bare_model_id(model_id: str) -> str:
    """Strip provider prefix from a catalog model_id.

    Provider-prefixed ids drop only the routing prefix; canonical model ids stay unchanged.
    """
    return model_id.rsplit("/", 1)[-1]


def _normalize_bfcl_name(name: str) -> str:
    """Normalize a BFCL model name to a bare model ID.

    Provider benchmark labels normalize to comparable lowercase ids.
    """
    name = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
    name = name.lower()
    name = re.sub(r"-\d{8,}$", "", name)
    return name


def _normalize_livebench_name(name: str) -> str:
    """Normalize a LiveBench model name to a bare model ID.

    Dated suffixes and benchmark-mode suffixes are removed before matching.
    """
    name = name.strip().lower()
    name = re.sub(r"-\d{8,}.*$", "", name)
    name = re.sub(r"-(base|thinking.*|high-effort|medium-effort|low-effort)$", "", name)
    return name


def _parse_pct(value: str) -> float:
    """Parse a percentage string like '77.47%' to float."""
    try:
        return float(str(value).replace("%", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _parse_price(value: Any) -> float | None:
    """Parse a price value to float (assumed per-million tokens)."""
    if value is None:
        return None
    try:
        return float(str(value).replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _normalize_arimxyer_index(value: Any) -> int:
    """Normalize an arimxyer benchmark index (0-57 scale) to 0-100."""
    try:
        score = float(value)
        return min(100, round(score / _ARIMXYER_INDEX_SCALE * 100))
    except (ValueError, TypeError):
        return 0


def _normalize_score(value: Any, scale: float = 100.0) -> int:
    """Normalize a benchmark score to 0-100 integer scale."""
    try:
        score = float(value)
        if score <= 1.0:
            return round(score * 100)
        if score <= scale:
            return round(score)
        return round((score / scale) * 100)
    except (ValueError, TypeError):
        return 0


def _livebench_avg(row: dict[str, Any], tasks: list[str]) -> float:
    """Compute average score across given task columns in a LiveBench row."""
    values = []
    for task in tasks:
        if task == "model":
            continue
        try:
            v = float(row.get(task, 0))
            values.append(v)
        except (ValueError, TypeError):
            pass
    return sum(values) / len(values) if values else 0.0


def _livebench_category_avg(row: dict[str, Any], tasks: list[str]) -> float | None:
    """Compute average score for a specific category of LiveBench tasks."""
    values = []
    for task in tasks:
        try:
            v = float(row.get(task, 0))
            values.append(v)
        except (ValueError, TypeError):
            pass
    if not values:
        return None
    return sum(values) / len(values)
