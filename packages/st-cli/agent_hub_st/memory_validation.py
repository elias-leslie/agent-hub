"""Validation and formatting helpers for memory episode standards."""

from __future__ import annotations

import re

import typer
from st_sdk.output import output_error

IMPERATIVE_VERBS = (
    "Use",
    "Never",
    "Always",
    "Check",
    "Follow",
    "Avoid",
    "Run",
    "Keep",
    "Prefer",
    "Treat",
    "Record",
    "Verify",
    "Fix",
    "Delete",
    "Remove",
    "Commit",
    "Push",
    "Restart",
    "Rebuild",
)
SAVE_EXAMPLE = """
Example:
  st memory save -s project --scope-id a-term -t reference \\
    -S "Network timeout evidence" \\
    "A timeout could indicate packet loss; compare successful requests before claiming a cause."

Summary: 10-40 characters. Content: non-empty text or Markdown.
Keep short, reusable knowledge in memory; put long explanations in the linked wiki.
Reusable cross-surface instructions belong in Agent Hub prompts.
"""

FORMAT_EXAMPLE = """
Optional structured formatting:
  st memory format --topic "Network evidence" \\
    --instruction "Compare successful requests before claiming a cause"
"""

SAVE_QUICKSTART = "Quickstart:\n" + SAVE_EXAMPLE
FORMAT_STANDARD_HELP = SAVE_QUICKSTART + FORMAT_EXAMPLE


def _normalize_sentence(text: str) -> str:
    """Trim and ensure sentence-ending punctuation."""
    cleaned = text.strip()
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        return f"{cleaned}."
    return cleaned


def _normalize_topic(topic: str) -> str:
    """Collapse internal whitespace and reject invalid topic text."""
    cleaned = re.sub(r"\s+", " ", topic.strip())
    if not cleaned:
        raise typer.BadParameter("Topic is required")
    if "**" in cleaned or ":" in cleaned or "\n" in cleaned:
        raise typer.BadParameter("Topic must be plain text without bold markers, colons, or newlines")
    if len(cleaned) > 79:
        raise typer.BadParameter("Topic must be 79 characters or fewer")
    return cleaned


def validate_episode_content_present(content: str) -> str:
    """Require non-empty episode content and return the original string."""
    if not content.strip():
        output_error("Content is required and cannot be blank.")
        raise typer.Exit(1)
    return content


def emit_save_quickstart_error(
    *,
    missing_summary: bool = False,
    missing_content: bool = False,
    blank_content: bool = False,
) -> None:
    """Print a self-contained `st memory save` quickstart error and exit."""
    problems: list[str] = []
    if missing_summary:
        problems.append("--summary")
    if missing_content:
        problems.append("content or --content-file")

    if blank_content and not missing_content:
        message = "st memory save content cannot be blank."
    elif problems:
        joined = " and ".join(problems)
        message = f"st memory save requires {joined}."
    else:
        message = "st memory save input is invalid."

    output_error(message)
    typer.echo(SAVE_QUICKSTART, err=True)
    raise typer.Exit(1)


def build_episode_content(
    topic: str,
    instruction: str,
    prohibition: str | None = None,
    why: str | None = None,
) -> str:
    """Build a standard memory episode body from structured parts."""
    cleaned_topic = _normalize_topic(topic)
    parts = [_normalize_sentence(instruction)]
    if prohibition:
        parts.append(_normalize_sentence(prohibition))
    if why:
        parts.append(_normalize_sentence(f"Why: {why}"))

    body = " ".join(part for part in parts if part)
    return f"**{cleaned_topic}**: {body}"


def suggest_summary(instruction: str, limit: int = 40) -> str:
    """Suggest a compact summary from the primary instruction."""
    summary = instruction.strip()
    if not summary:
        return ""

    summary = re.sub(rf"^(?:{'|'.join(IMPERATIVE_VERBS)})\s+", "", summary, flags=re.IGNORECASE)
    summary = summary.rstrip(".!? ")
    if len(summary) <= limit:
        return summary

    clipped = summary[:limit].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(".!? ")


def validate_format_standard(content: str, summary: str, tier: str) -> tuple[list[str], list[str]]:
    """Validate record fields without imposing a prose style."""
    errors: list[str] = []
    if tier not in {"mandate", "guardrail", "reference", "archive"}:
        errors.append(f"Unsupported tier {tier}")
    if not content.strip():
        errors.append("Content cannot be blank")
    if not 10 <= len(summary) <= 40:
        errors.append(f"Summary needs 10-40 characters (got {len(summary)})")
    return errors, []


def validate_summary_length(summary: str) -> None:
    """Validate summary length and raise error if invalid."""
    if len(summary) > 40:
        output_error(f"Summary too long ({len(summary)} chars). Keep it under 40 chars.")
        typer.echo(SAVE_QUICKSTART, err=True)
        raise typer.Exit(1)


def validate_content_format(content: str, summary: str, tier: str) -> None:
    """Validate content format and raise error if invalid."""
    validate_episode_content_present(content)
    format_errors, _hints = validate_format_standard(content, summary, tier)
    if format_errors:
        output_error("Memory validation failed:")
        for err in format_errors:
            typer.echo(f"  {err}", err=True)
        typer.echo(FORMAT_STANDARD_HELP, err=True)
        raise typer.Exit(1)


def validate_memory_authoring(label: str, content: str, summary: str, tier: str) -> None:
    """Validate authoring fields, retaining the original content."""
    validate_content_format(content, summary, tier)
