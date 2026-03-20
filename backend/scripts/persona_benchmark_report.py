"""Report rendering for persona model benchmark runs."""

from __future__ import annotations

from scripts.persona_benchmark_eval import PersonaBenchmarkAttempt, PersonaBenchmarkRun
from scripts.persona_display import normalize_persona_name


def _format_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _render_attempt_detail(attempt: PersonaBenchmarkAttempt) -> str:
    outcome = "PASS" if attempt.passed else (attempt.failure_kind or "failed").upper()
    used_tools = ", ".join(attempt.used_tool_names)
    return (
        f"| {attempt.model_id} | {attempt.case_id} | {attempt.run_number} | "
        f"{attempt.composite_score:.1f} | {attempt.latency_ms} | {attempt.total_tokens} | "
        f"{attempt.turns} | {attempt.tool_calls_count} | {used_tools} | {outcome} | "
        f"{attempt.failure_detail or ''} |"
    )


def generate_markdown_report(
    run: PersonaBenchmarkRun,
    *,
    persona_name: str = "Persona",
) -> str:
    """Render a full markdown report for a benchmark run."""
    display_name = normalize_persona_name(persona_name)
    lines = [
        f"# {display_name} Model Benchmark",
        "",
        f"**Benchmark ID:** `{run.benchmark_id}`",
        f"**Project ID:** `{run.project_id}`",
        f"**Models:** {', '.join(f'`{model}`' for model in run.models)}",
        f"**Cases:** {', '.join(f'`{case_id}`' for case_id in run.case_ids)}",
        f"**Runs per case:** {run.runs_per_case}",
        f"**Started:** {run.started_at}",
        f"**Completed:** {run.completed_at}",
        "",
        "## Ranking",
        "",
        "| Rank | Model | Avg Score | Pass Rate | Infra Failures | Model Failures | Avg Latency (ms) | Avg Tokens | Avg Turns | Avg Tool Calls |",
        "|------|-------|-----------|-----------|----------------|----------------|------------------|------------|-----------|----------------|",
    ]

    for rank, summary in enumerate(run.summaries, start=1):
        lines.append(
            f"| {rank} | `{summary.model_id}` | {summary.avg_composite_score:.1f} | "
            f"{_format_pct(summary.pass_rate)} | {summary.infra_failures} | "
            f"{summary.model_failures} | {summary.avg_latency_ms:.0f} | "
            f"{summary.avg_total_tokens:.0f} | {summary.avg_turns:.1f} | "
            f"{summary.avg_tool_calls:.1f} |"
        )

    lines.extend(
        [
            "",
            "## Attempt Details",
            "",
            "| Model | Case | Run | Score | Latency (ms) | Tokens | Turns | Tool Calls | Used Tools | Outcome | Detail |",
            "|-------|------|-----|-------|--------------|--------|-------|------------|------------|---------|--------|",
        ]
    )

    ordered_attempts = sorted(
        run.attempts,
        key=lambda attempt: (attempt.model_id, attempt.case_id, attempt.run_number),
    )
    for attempt in ordered_attempts:
        lines.append(_render_attempt_detail(attempt))

    return "\n".join(lines) + "\n"
