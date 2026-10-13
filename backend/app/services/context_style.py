"""Deterministic, advisory style check for agent-only context (owner directive 2026-10-11).

Prompts, memories and generated blocks are read only by agents: terse imperative
rules, no human-facing filler. Warnings never block a write; they are returned to
the writer and surfaced by context-governance deterministic findings.
"""
from __future__ import annotations

import re

from app.services.memory.budget import count_tokens

AUTHORING_HINT = (
    "Agent-only context: terse imperative rules; no filler, hedging or restated headings; "
    "keep every condition, command, path and number."
)

PADDING = re.compile(
    r"(?i)\b(please|it is (?:important|essential|crucial) (?:to|that)|make sure (?:to|that)|be sure to|"
    r"in order to|keep in mind|note that|remember to|don't forget|feel free|as mentioned|"
    r"it should be noted|as an ai|i hope|happy to help)\b"
)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
COMMAND_HEAD = re.compile(r"[a-z][\w.-]*")
HOWTO_MIN_COMMANDS = 2
GROWTH_RATIO = 1.25
GROWTH_MIN_TOKENS = 30


def style_warnings(content: str | None, previous: str | None = None) -> list[str]:
    """Return short warnings for padding phrases and large token growth."""
    if not content:
        return []
    warnings: list[str] = []
    found = sorted({m.group(0).lower() for m in PADDING.finditer(content)})
    if found:
        warnings.append(f"padding: {', '.join(found)}")
    if previous:
        before, after = count_tokens(previous), count_tokens(content)
        if after - before >= GROWTH_MIN_TOKENS and after > before * GROWTH_RATIO:
            warnings.append(f"token growth: {before}->{after}")
    if warnings:
        warnings.append(AUTHORING_HINT)
    return warnings


def _is_flag(token: str) -> bool:
    """-x, --xyz, or a bare - / --."""
    dashes = len(token) - len(token.lstrip("-"))
    return 1 <= dashes <= 2 and (token in ("-", "--") or token[dashes].isalpha())


def _looks_like_command(span: str) -> bool:
    """A lowercase command head followed by at least one flag token (token checks, no backtracking regex)."""
    head, _, rest = span.partition(" ")
    return bool(rest) and COMMAND_HEAD.fullmatch(head) is not None and any(_is_flag(t) for t in rest.split())


def memory_style_warnings(content: str | None, previous: str | None = None) -> list[str]:
    """style_warnings plus a tool how-to nudge: commands belong in ST surfaces, not memory."""
    warnings = style_warnings(content, previous)
    commands = [span for span in CODE_SPAN.findall(content or "") if _looks_like_command(span)]
    if len(commands) >= HOWTO_MIN_COMMANDS:
        warnings.insert(0, f"tool how-to ({len(commands)} commands): register an ST surface or failure-hook hint, not memory")
    return warnings
