"""Context bloat warnings fire only for over-budget or repeated delivered text."""

from __future__ import annotations

from agent_hub_st.context_budget import PROMPT_BLOCK_BUDGET, TOTAL_BUDGET, context_warnings


def _block(block_id: str, content: str, tokens: int = 10, kind: str = "prompt") -> dict[str, object]:
    return {"block_id": block_id, "kind": kind, "content": content, "estimated_tokens": tokens}


def test_clean_context_is_silent() -> None:
    blocks = [_block("prompt:a", "Lead with the outcome."), _block("prompt:b", "Exclude snapshots.")]
    assert context_warnings(blocks) == []


def test_over_budget_block_and_total_warn() -> None:
    blocks = [_block("prompt:big", "x", PROMPT_BLOCK_BUDGET + 1), _block("tool", "y", TOTAL_BUDGET, "tool_capabilities")]
    warnings = context_warnings(blocks)
    assert warnings[0].startswith(f"CONTEXT_WARN:total={TOTAL_BUDGET + PROMPT_BLOCK_BUDGET + 1}tok")
    assert f"CONTEXT_WARN:over_budget prompt:big={PROMPT_BLOCK_BUDGET + 1}tok>budget={PROMPT_BLOCK_BUDGET}" in warnings
    assert any("over_budget tool=" in warning for warning in warnings)


def test_repeated_phrase_across_blocks_warns_once_per_pair() -> None:
    phrase = "never run raw pytest vitest biome tsc ruff for quality gates"
    blocks = [_block("prompt:a", f"Rule: {phrase}."), _block("tools", f"careful: {phrase} again {phrase}")]
    warnings = context_warnings(blocks)
    assert len(warnings) == 1 and warnings[0].startswith('CONTEXT_WARN:duplicate prompt:a~tools "')


def test_focus_limits_block_findings_and_output_is_capped() -> None:
    blocks = [_block(f"prompt:{i}", "x", PROMPT_BLOCK_BUDGET + 1) for i in range(3)]
    assert context_warnings(blocks, 0, focus="prompt:1") == [
        f"CONTEXT_WARN:over_budget prompt:1={PROMPT_BLOCK_BUDGET + 1}tok>budget={PROMPT_BLOCK_BUDGET}"
    ]
    many = [_block(f"prompt:{i}", "x", PROMPT_BLOCK_BUDGET + 1) for i in range(10)]
    capped = context_warnings(many, 0)
    assert len(capped) == 6 and capped[-1].startswith("CONTEXT_WARN:+5 more")
