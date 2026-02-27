"""Report generator for benchmark results."""

from __future__ import annotations

from tests.benchmarks.models import BenchmarkResult


def generate_comparison_table(results: list[BenchmarkResult]) -> str:
    """Generate a markdown comparison table from benchmark results."""
    if not results:
        return "No results to report."

    # Build header
    headers = ["Metric"]
    for r in results:
        headers.append(f"{r.approach} ({r.approach_name})")

    # Build rows
    rows: list[list[str]] = [
        _row("Total latency (ms)", results, lambda r: str(r.total_latency_ms)),
        _row("Input tokens", results, lambda r: str(r.total_input_tokens)),
        _row("Output tokens", results, lambda r: str(r.total_output_tokens)),
        _row("Cache read tokens", results, lambda r: str(r.total_cache_read_tokens)),
        _row("Cache creation tokens", results, lambda r: str(r.total_cache_creation_tokens)),
        _row("Peak RSS (MB)", results, lambda r: f"{r.peak_rss_mb:.1f}"),
        _row("Subprocess spawns", results, lambda r: str(r.subprocess_count)),
        _row("Turns", results, lambda r: str(r.num_turns)),
        _row("Permission checks", results, lambda r: str(r.permission_checks)),
        _row("Permission denials", results, lambda r: str(r.permission_denials)),
        _row("Correct", results, lambda r: "Yes" if r.correct else "NO"),
        _row("Errors", results, lambda r: str(len(r.errors)) if r.errors else "0"),
    ]

    return _format_table(headers, rows)


def generate_run_comparison(
    all_runs: dict[str, list[BenchmarkResult]],
) -> str:
    """Generate a comparison across multiple runs per approach."""
    if not all_runs:
        return "No runs to report."

    lines: list[str] = ["## Per-Run Results\n"]

    for approach, runs in sorted(all_runs.items()):
        lines.append(f"### Approach {approach}: {runs[0].approach_name}\n")
        headers = ["Run", "Latency (ms)", "Input Tokens", "Output Tokens",
                    "Cache Read", "Turns", "Correct"]
        rows: list[list[str]] = []
        for i, r in enumerate(runs, 1):
            rows.append([
                str(i),
                str(r.total_latency_ms),
                str(r.total_input_tokens),
                str(r.total_output_tokens),
                str(r.total_cache_read_tokens),
                str(r.num_turns),
                "Yes" if r.correct else "NO",
            ])

        # Averages
        avg_latency = sum(r.total_latency_ms for r in runs) // len(runs)
        avg_input = sum(r.total_input_tokens for r in runs) // len(runs)
        avg_output = sum(r.total_output_tokens for r in runs) // len(runs)
        avg_cache = sum(r.total_cache_read_tokens for r in runs) // len(runs)
        avg_turns = sum(r.num_turns for r in runs) / len(runs)
        all_correct = all(r.correct for r in runs)
        rows.append([
            "**Avg**",
            f"**{avg_latency}**",
            f"**{avg_input}**",
            f"**{avg_output}**",
            f"**{avg_cache}**",
            f"**{avg_turns:.1f}**",
            f"**{'Yes' if all_correct else 'NO'}**",
        ])

        lines.append(_format_table(headers, rows))
        lines.append("")

    return "\n".join(lines)


def generate_turn_details(results: list[BenchmarkResult]) -> str:
    """Generate per-turn detail tables for each approach."""
    lines: list[str] = ["## Per-Turn Details\n"]

    for r in results:
        lines.append(f"### Approach {r.approach}: {r.approach_name}\n")
        if not r.turns:
            lines.append("No turn data available.\n")
            continue

        headers = ["Turn", "Latency (ms)", "In Tokens", "Out Tokens",
                    "Cache Read", "Tools", "Results"]
        rows: list[list[str]] = []
        for t in r.turns:
            tools_str = ", ".join(t.tool_calls) if t.tool_calls else "-"
            results_str = "; ".join(t.tool_results[:2]) if t.tool_results else "-"
            if len(results_str) > 60:
                results_str = results_str[:57] + "..."
            rows.append([
                str(t.turn_number),
                str(t.latency_ms),
                str(t.input_tokens),
                str(t.output_tokens),
                str(t.cache_read_tokens),
                tools_str,
                results_str,
            ])
        lines.append(_format_table(headers, rows))

        if r.errors:
            lines.append(f"\nErrors: {'; '.join(r.errors)}\n")
        lines.append("")

    return "\n".join(lines)


def generate_full_report(
    all_runs: dict[str, list[BenchmarkResult]],
    model: str,
    num_runs: int,
    verbose: bool = False,
) -> str:
    """Generate the complete benchmark report."""
    lines: list[str] = [
        "# Tool Execution Benchmark Results\n",
        f"- **Model**: {model}",
        f"- **Runs per approach**: {num_runs}",
        "- **Date**: (see file timestamp)\n",
    ]

    # Average results for comparison table
    avg_results: list[BenchmarkResult] = []
    for approach in sorted(all_runs.keys()):
        runs = all_runs[approach]
        if not runs:
            continue
        avg = BenchmarkResult(
            approach=approach,
            approach_name=runs[0].approach_name,
            total_latency_ms=sum(r.total_latency_ms for r in runs) // len(runs),
            total_input_tokens=sum(r.total_input_tokens for r in runs) // len(runs),
            total_output_tokens=sum(r.total_output_tokens for r in runs) // len(runs),
            total_cache_read_tokens=sum(r.total_cache_read_tokens for r in runs) // len(runs),
            total_cache_creation_tokens=sum(r.total_cache_creation_tokens for r in runs) // len(runs),
            peak_rss_mb=max(r.peak_rss_mb for r in runs),
            subprocess_count=runs[0].subprocess_count,
            num_turns=round(sum(r.num_turns for r in runs) / len(runs)),
            permission_checks=sum(r.permission_checks for r in runs) // len(runs),
            permission_denials=sum(r.permission_denials for r in runs) // len(runs),
            correct=all(r.correct for r in runs),
            errors=[e for r in runs for e in r.errors],
        )
        avg_results.append(avg)

    lines.append("## Summary (Averaged)\n")
    lines.append(generate_comparison_table(avg_results))
    lines.append("")
    lines.append(generate_run_comparison(all_runs))

    if verbose:
        # Add turn details for the last run of each approach
        last_runs = [runs[-1] for runs in all_runs.values() if runs]
        lines.append(generate_turn_details(last_runs))

    # Winner analysis
    lines.append("## Analysis\n")
    if avg_results:
        correct_results = [r for r in avg_results if r.correct]
        if not correct_results:
            lines.append("**No approach produced correct results.** All are disqualified.\n")
        else:
            # Sort by total tokens (input + output), then latency
            by_cost = sorted(correct_results, key=lambda r: r.total_input_tokens + r.total_output_tokens)
            by_latency = sorted(correct_results, key=lambda r: r.total_latency_ms)

            lines.append(f"**Lowest token cost**: {by_cost[0].approach} ({by_cost[0].approach_name}) "
                         f"— {by_cost[0].total_input_tokens + by_cost[0].total_output_tokens} total tokens\n")
            lines.append(f"**Lowest latency**: {by_latency[0].approach} ({by_latency[0].approach_name}) "
                         f"— {by_latency[0].total_latency_ms}ms\n")

            has_permissions = [r for r in correct_results if r.permission_checks > 0]
            no_permissions = [r for r in correct_results if r.permission_checks == 0]
            if has_permissions:
                lines.append(f"**With permissions**: {', '.join(r.approach for r in has_permissions)}")
            if no_permissions:
                lines.append(f"**No permissions (speed-only)**: {', '.join(r.approach for r in no_permissions)}")

    return "\n".join(lines)


def _row(label: str, results: list[BenchmarkResult], fn: any) -> list[str]:
    """Build a table row."""
    return [label] + [fn(r) for r in results]


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format a markdown table with right-aligned numeric columns."""
    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    # Build table
    lines: list[str] = []

    # Header
    header_cells = [headers[0].ljust(widths[0])]
    for i, h in enumerate(headers[1:], 1):
        header_cells.append(h.rjust(widths[i]))
    lines.append("| " + " | ".join(header_cells) + " |")

    # Separator
    sep_cells = ["-" * widths[0]]
    for w in widths[1:]:
        sep_cells.append("-" * w)
    lines.append("| " + " | ".join(sep_cells) + " |")

    # Data rows
    for row in rows:
        cells = [row[0].ljust(widths[0])]
        for i, cell in enumerate(row[1:], 1):
            if i < len(widths):
                cells.append(cell.rjust(widths[i]))
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)
