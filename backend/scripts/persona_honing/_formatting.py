"""Formatting helpers for persona honing prompts and summaries."""
from __future__ import annotations

from typing import Any

from scripts.persona_honing._models import PersonaHoningIteration


def _format_delta_block(label: str, delta: dict[str, Any] | None) -> str:
    if not isinstance(delta, dict):
        return f"- {label}: unavailable"
    return f"- {label}: mean={delta.get('mean_delta')} ci=[{delta.get('ci_low')}, {delta.get('ci_high')}]"


def _format_experiment_summary_block(summary: dict[str, Any] | None) -> str:
    if not isinstance(summary, dict):
        return "- not available"
    baseline = dict(summary.get("baseline") or {})
    candidate = dict(summary.get("candidate") or {})
    return "\n".join([
        f"- decision={summary.get('decision')} reason={summary.get('decision_reason')}",
        (
            f"- baseline: runs={baseline.get('run_count')} score={baseline.get('avg_score')} "
            f"pass_rate={baseline.get('avg_pass_rate')} tools={baseline.get('avg_tool_calls')}"
        ),
        (
            f"- candidate: runs={candidate.get('run_count')} score={candidate.get('avg_score')} "
            f"pass_rate={candidate.get('avg_pass_rate')} tools={candidate.get('avg_tool_calls')}"
        ),
        _format_delta_block("score_delta", summary.get("score_delta")),
        _format_delta_block("pass_rate_delta", summary.get("pass_rate_delta")),
        _format_delta_block("tool_call_delta", summary.get("tool_call_delta")),
    ])


def _format_improvement_summary_block(record: PersonaHoningIteration) -> str:
    parsed = dict(record.improvement_parsed or {})
    changes = parsed.get("changes_applied")
    next_focus = parsed.get("next_focus")
    lines = [
        f"- summary={parsed.get('summary') or '(none)'}",
        f"- tools={', '.join(record.improvement_tools or []) or 'none'}",
    ]
    if isinstance(changes, list) and changes:
        lines.append("- changes_applied=" + "; ".join(str(item) for item in changes))
    if isinstance(next_focus, list) and next_focus:
        lines.append("- next_focus=" + "; ".join(str(item) for item in next_focus))
    return "\n".join(lines)
