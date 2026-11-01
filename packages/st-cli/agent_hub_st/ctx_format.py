"""Terse text formatting for ``st ctx``: tokens as 48.4K, unknown as an em dash (never 0), one line per fact.

Every reader is tolerant: Agent Hub may add response fields, so nothing here indexes a key that could be absent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

UNKNOWN = "—"
TOOL = "st ctx"  # X-Tool-Name of every request
ON_DEMAND = "context cost"
TASKS = ("context-cost", "prompt-tuning", "agent-admin")
MAX_LINES = 15


def obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def rows(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def tok(value: Any, *, sign: bool = False) -> str:
    """48400 -> 48.4K, 940 -> 940; None -> —."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return UNKNOWN
    number = int(round(value))
    prefix = "+" if sign and number > 0 else ""
    if abs(number) >= 1000:
        return f"{prefix}{number / 1000:.1f}K"
    return f"{prefix}{number}"


def pct(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return UNKNOWN
    return f"{value:+.0f}%"


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def when(value: Any) -> str:
    """2026-11-01T14:53:44Z -> 11-01 14:53Z."""
    parsed = parse_time(value)
    return parsed.astimezone(UTC).strftime("%m-%d %H:%MZ") if parsed else UNKNOWN


def day(value: Any) -> str:
    parsed = parse_time(value)
    return parsed.astimezone(UTC).strftime("%m-%d") if parsed else UNKNOWN


def age(value: Any, *, now: datetime | None = None) -> str:
    parsed = parse_time(value)
    if parsed is None:
        return UNKNOWN
    seconds = max(0, int(((now or datetime.now(UTC)) - parsed).total_seconds()))
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def short(value: Any, width: int) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text if len(text) <= width else text[: max(width - 1, 1)] + "…"


def fp(value: Any) -> str:
    return str(value)[:8] if value else UNKNOWN


def table(lines: list[list[str]], *, indent: str = "") -> list[str]:
    """Left-aligned columns, the last one unpadded."""
    if not lines:
        return []
    widths = [max(len(line[i]) for line in lines if i < len(line)) for i in range(max(len(line) for line in lines))]
    return [indent + "  ".join(cell.ljust(widths[i]) if i < len(line) - 1 else cell for i, cell in enumerate(line)).rstrip()
            for line in lines]


def emit(lines: list[str]) -> None:
    """Print at most MAX_LINES; a longer answer ends with a pointer to --json instead of running on."""
    shown = lines if len(lines) <= MAX_LINES else [*lines[: MAX_LINES - 1], f"… {len(lines) - MAX_LINES + 1} more lines (--json)"]
    print("\n".join(line.rstrip() for line in shown))
