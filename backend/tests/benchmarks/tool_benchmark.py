"""Main benchmark runner for comparing tool execution approaches.

Usage:
    cd backend
    CLAUDECODE= .venv/bin/python -m tests.benchmarks.tool_benchmark \
        --runs 3 --model haiku --output results.md

Options:
    --runs N        Number of runs per approach (default 3)
    --model MODEL   Claude model to use (default haiku)
    --approaches    Comma-separated list of approaches to run (default A,B,D)
    --output PATH   Where to write results markdown (default stdout)
    --verbose       Print per-turn details
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from tests.benchmarks.models import BenchmarkResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

async def run_single_approach(
    approach: str,
    model: str,
    working_dir: str | None,
    project_id: str | None,
) -> BenchmarkResult:
    """Run a single approach and return its result."""
    if approach == "A":
        from tests.benchmarks.approach_a import run_approach_a
        return await run_approach_a(model, working_dir, project_id)
    elif approach == "B":
        from tests.benchmarks.approach_b import run_approach_b
        return await run_approach_b(model, working_dir, project_id)
    elif approach == "D":
        from tests.benchmarks.approach_d import run_approach_d
        return await run_approach_d(model, working_dir, project_id)
    else:
        msg = f"Unknown approach: {approach}"
        raise ValueError(msg)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark tool execution approaches")
    parser.add_argument("--runs", type=int, default=3, help="Runs per approach (default 3)")
    parser.add_argument("--model", default="haiku", help="Claude model (default haiku)")
    parser.add_argument("--approaches", default="A,B,D",
                        help="Comma-separated approaches (default A,B,D)")
    parser.add_argument("--output", help="Output file path (default stdout)")
    parser.add_argument("--verbose", action="store_true", help="Print per-turn details")
    parser.add_argument("--project-id", default="benchmark-test",
                        help="Project ID for permission checks (default benchmark-test)")
    parser.add_argument("--working-dir", default=None,
                        help="Working directory (default /tmp/benchmark-test)")
    args = parser.parse_args()

    approaches = [a.strip().upper() for a in args.approaches.split(",")]
    working_dir = args.working_dir or "/tmp/benchmark-test"

    # Ensure working directory exists
    import os
    os.makedirs(working_dir, exist_ok=True)

    logger.info("=== Tool Execution Benchmark ===")
    logger.info("Model: %s | Runs: %d | Approaches: %s", args.model, args.runs, approaches)
    logger.info("Working dir: %s | Project: %s", working_dir, args.project_id)

    all_runs: dict[str, list[BenchmarkResult]] = {a: [] for a in approaches}

    for run_num in range(1, args.runs + 1):
        logger.info("\n--- Run %d/%d ---", run_num, args.runs)

        for approach in approaches:
            logger.info("Running approach %s (run %d)...", approach, run_num)
            try:
                result = await run_single_approach(
                    approach=approach,
                    model=args.model,
                    working_dir=working_dir,
                    project_id=args.project_id,
                )
                all_runs[approach].append(result)

                logger.info(
                    "  %s: %dms, %d input tokens, %d output tokens, "
                    "%d cache read, %d turns, correct=%s%s",
                    approach,
                    result.total_latency_ms,
                    result.total_input_tokens,
                    result.total_output_tokens,
                    result.total_cache_read_tokens,
                    result.num_turns,
                    result.correct,
                    f", errors={result.errors}" if result.errors else "",
                )

            except Exception as e:
                logger.exception("Failed to run approach %s (run %d)", approach, run_num)
                error_result = BenchmarkResult(
                    approach=approach,
                    approach_name=f"Approach {approach} (FAILED)",
                    errors=[str(e)],
                )
                all_runs[approach].append(error_result)

    # Generate report
    from tests.benchmarks.report import generate_full_report

    report = generate_full_report(
        all_runs=all_runs,
        model=args.model,
        num_runs=args.runs,
        verbose=args.verbose,
    )

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        logger.info("Report written to %s", args.output)
    else:
        print("\n" + report)


if __name__ == "__main__":
    asyncio.run(main())
