"""Cheap bloat check for delivered startup context.

Emits short ``CONTEXT_WARN`` lines only when the delivery or one block exceeds
its token budget, or two blocks repeat the same phrase. Silent otherwise, so it
costs nothing in normal output.
"""

from __future__ import annotations

import re
from typing import Any

TOTAL_BUDGET = 3_000
PROMPT_BLOCK_BUDGET = 600
GENERATED_BLOCK_BUDGET = 1_200
_GENERATED_KINDS = frozenset({"project_index", "tool_capabilities"})
_SHINGLE_WORDS = 8
_MAX_LINES = 6
_WORD = re.compile(r"[a-z0-9/._-]+")


def _shingles(text: str) -> dict[tuple[str, ...], int]:
    words = _WORD.findall(text.lower())
    out: dict[tuple[str, ...], int] = {}
    for i in range(len(words) - _SHINGLE_WORDS + 1):
        out.setdefault(tuple(words[i : i + _SHINGLE_WORDS]), i)
    return out


def _budget(block: dict[str, Any]) -> int:
    return GENERATED_BLOCK_BUDGET if block.get("kind") in _GENERATED_KINDS else PROMPT_BLOCK_BUDGET


def context_warnings(
    blocks: list[dict[str, Any]],
    total_tokens: int | None = None,
    *,
    focus: str | None = None,
    scope: str | None = None,
) -> list[str]:
    """Return warning lines; ``focus`` limits block-level findings to one block id.

    ``scope`` names the measured delivery (project id or ``global``): the total
    depends on which project's prompts, index and continuity the cwd selects.
    """
    warnings: list[str] = []
    total = total_tokens if total_tokens is not None else sum(int(b.get("estimated_tokens") or 0) for b in blocks)
    if total > TOTAL_BUDGET:
        warnings.append(f"CONTEXT_WARN:total={total}tok>budget={TOTAL_BUDGET}" + (f" scope={scope}" if scope else ""))
    seen: dict[tuple[str, ...], str] = {}
    for block in blocks:
        block_id = str(block.get("block_id") or "?")
        tokens = int(block.get("estimated_tokens") or 0)
        if tokens > _budget(block) and focus in (None, block_id):
            warnings.append(f"CONTEXT_WARN:over_budget {block_id}={tokens}tok>budget={_budget(block)}")
        reported: set[str] = set()
        for shingle in _shingles(str(block.get("content") or "")):
            other = seen.get(shingle)
            if other is None:
                seen[shingle] = block_id
            elif other != block_id and other not in reported and focus in (None, block_id, other):
                reported.add(other)
                warnings.append(f'CONTEXT_WARN:duplicate {other}~{block_id} "{" ".join(shingle)}"')
    if len(warnings) > _MAX_LINES:
        extra = len(warnings) - _MAX_LINES + 1
        warnings = [*warnings[: _MAX_LINES - 1], f"CONTEXT_WARN:+{extra} more (st --no-compact mandates)"]
    return warnings
