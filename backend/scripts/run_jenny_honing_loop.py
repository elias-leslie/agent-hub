#!/usr/bin/env python3
"""Run iterative Jenny benchmark passes and prompt Jenny to self-correct between runs."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = ROOT / "backend" / ".venv" / "bin" / "python"

if (
    VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
    and os.environ.get("JENNY_HONING_NO_REEXEC") != "1"
):
    os.environ["JENNY_HONING_NO_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "packages" / "agent-hub-client"))

from agent_hub import AsyncAgentHubClient

from app.services.agent_benchmark_service import (
    capture_benchmark_config_snapshot,
    persist_benchmark_payload,
)
from scripts.jenny_benchmark_cases import DEFAULT_JENNY_BENCHMARK_MODELS, get_jenny_benchmark_cases
from scripts.jenny_benchmark_eval import JennyBenchmarkAttempt, JennyBenchmarkRun
from scripts.jenny_benchmark_report import generate_markdown_report
from scripts.run_jenny_model_benchmark import (
    _fetch_used_tool_names,
    _parse_csv,
    _resolve_client_id,
    build_persistence_payload,
    derive_suite_id,
    run_benchmark,
)

_HONING_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "changes_applied": {
            "type": "array",
            "items": {"type": "string"},
        },
        "next_focus": {
            "type": "array",
            "items": {"type": "string"},
        },
        "durable_learning_saved": {"type": "boolean"},
    },
    "required": ["summary", "changes_applied", "next_focus", "durable_learning_saved"],
}

_REFERENCE_NOTES = [
    (
        "Auto-Claude inspiration: the learning loop should retrieve shared patterns/gotchas "
        "before acting, and durable lessons belong in shared memory rather than ad hoc notes."
    ),
    (
        "OpenClaw inspiration: keep fallback/model decisions observable and simple; prefer "
        "clear, inspectable adaptation over extra defensive machinery."
    ),
]


@dataclass
class JennyHoningIteration:
    """One benchmark + self-improvement cycle."""

    iteration: int
    benchmark_id: str
    top_model: str | None
    top_score: float
    failing_attempts: int
    benchmark_report_path: str | None
    failure_clusters: list[dict[str, Any]] | None = None
    persistent_failure_clusters: list[dict[str, Any]] | None = None
    persisted_run_id: str | None = None
    improvement_session_id: str | None = None
    improvement_tools: list[str] | None = None
    improvement_content: str | None = None
    improvement_parsed: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _group_failures(attempts: list[JennyBenchmarkAttempt]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for attempt in attempts:
        if attempt.passed:
            continue
        key = (attempt.case_id, attempt.failure_detail or "failed")
        bucket = grouped.setdefault(
            key,
            {
                "case_id": attempt.case_id,
                "failure_detail": attempt.failure_detail or "failed",
                "count": 0,
                "models": set(),
                "avg_score_total": 0.0,
            },
        )
        bucket["count"] += 1
        bucket["models"].add(attempt.model_id)
        bucket["avg_score_total"] += attempt.composite_score

    ranked: list[dict[str, Any]] = []
    for bucket in grouped.values():
        ranked.append(
            {
                "case_id": bucket["case_id"],
                "failure_detail": bucket["failure_detail"],
                "count": bucket["count"],
                "models": sorted(bucket["models"]),
                "avg_score": round(bucket["avg_score_total"] / bucket["count"], 1),
            }
        )
    ranked.sort(key=lambda item: (-item["count"], item["avg_score"], item["case_id"]))
    return ranked


def _cluster_key(cluster: dict[str, Any]) -> tuple[str, str]:
    return (
        str(cluster.get("case_id", "")),
        str(cluster.get("failure_detail", "")),
    )


def _diff_failure_clusters(
    previous: list[dict[str, Any]] | None,
    current: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (persistent, new, resolved) clusters across iterations."""
    previous_map = {_cluster_key(cluster): cluster for cluster in previous or []}
    current_map = {_cluster_key(cluster): cluster for cluster in current}

    persistent = [
        current_map[key]
        for key in current_map
        if key in previous_map
    ]
    new = [
        current_map[key]
        for key in current_map
        if key not in previous_map
    ]
    resolved = [
        previous_map[key]
        for key in previous_map
        if key not in current_map
    ]
    return persistent, new, resolved


def _render_cluster_block(clusters: list[dict[str, Any]], label: str) -> str:
    if not clusters:
        return f"{label}:\n- none"

    lines = [f"{label}:"]
    for cluster in clusters:
        models = ", ".join(cluster.get("models", []))
        lines.append(
            f"- case={cluster['case_id']} count={cluster['count']} avg_score={cluster['avg_score']} "
            f"models={models} detail={cluster['failure_detail']}"
        )
    return "\n".join(lines)


def _parse_improvement_content(content: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def build_honing_prompt(
    run: JennyBenchmarkRun,
    iteration: int,
    previous_clusters: list[dict[str, Any]] | None = None,
    max_failures: int = 6,
) -> str:
    """Build the persona self-improvement prompt for one benchmark run."""
    current_clusters = _group_failures(run.attempts)
    persistent_clusters, new_clusters, resolved_clusters = _diff_failure_clusters(
        previous_clusters,
        current_clusters,
    )
    ranking_lines = []
    for index, summary in enumerate(run.summaries[:3], start=1):
        ranking_lines.append(
            f"- rank={index} model={summary.model_id} avg_score={summary.avg_composite_score:.1f} "
            f"pass_rate={summary.pass_rate:.3f} avg_tools={summary.avg_tool_calls:.1f}"
        )

    ranking_block = "\n".join(ranking_lines) if ranking_lines else "- none"
    reference_block = "\n".join(f"- {note}" for note in _REFERENCE_NOTES)
    failure_block = _render_cluster_block(current_clusters[:max_failures], "Top failure clusters")
    persistent_block = _render_cluster_block(
        persistent_clusters[:max_failures],
        "Persistent unresolved clusters from the previous iteration",
    )
    new_block = _render_cluster_block(new_clusters[:max_failures], "New clusters this iteration")
    resolved_block = _render_cluster_block(
        resolved_clusters[:max_failures],
        "Resolved clusters since the previous iteration",
    )

    return (
        f"You are Jenny reviewing your own benchmark results for honing iteration {iteration}.\n\n"
        "Your job is to improve your own operating model only where the evidence justifies it.\n"
        "Stay inside persona-internal adaptation work: heartbeat instructions, model review, "
        "performance logging, and durable memory. Do not create or dispatch project tasks.\n\n"
        "Benchmark ranking:\n"
        f"{ranking_block}\n\n"
        f"{failure_block}\n\n"
        f"{persistent_block}\n\n"
        f"{new_block}\n\n"
        f"{resolved_block}\n\n"
        "Reference heuristics to borrow when relevant:\n"
        f"{reference_block}\n\n"
        "Required behavior:\n"
        "- Diagnose the canonical layer first: heartbeat instructions, memory retrieval, observability, or model config.\n"
        "- When reviewing your own performance history, use agent_slug=\"persona\" rather than the display name Jenny.\n"
        "- If you change heartbeat instructions, read them first and make a small targeted edit.\n"
        "- If model assignment looks implicated, inspect model/performance tools before changing config.\n"
        "- Log a performance observation if the benchmark exposed a real recurring issue or confirmed an improvement.\n"
        "- Save durable memory only for reusable cross-session lessons.\n"
        "- Do not add speculative retry/safety mechanisms without demonstrated need.\n\n"
        "Return JSON only with fields summary, changes_applied, next_focus, durable_learning_saved."
    )


async def _run_improvement_pass(
    *,
    client: AsyncAgentHubClient,
    project_id: str,
    iteration: int,
    run: JennyBenchmarkRun,
    previous_clusters: list[dict[str, Any]] | None,
    timeout_seconds: float,
) -> tuple[str | None, str, list[str], dict[str, Any] | None]:
    """Prompt Jenny to improve herself based on benchmark failures."""
    response = await client.complete(
        messages=[{"role": "user", "content": build_honing_prompt(run, iteration, previous_clusters)}],
        project_id=project_id,
        agent_slug="persona",
        external_id=f"jenny-honing:{run.benchmark_id}:iteration-{iteration}",
        enable_caching=False,
        skip_cache=True,
        use_memory=True,
        max_turns=12,
        working_dir=str(ROOT),
        execute_tools=True,
        timeout_seconds=timeout_seconds,
        response_format={"type": "json_object", "schema": _HONING_RESPONSE_SCHEMA},
    )
    used_tools = await _fetch_used_tool_names(response.session_id)
    return response.session_id, response.content, used_tools, _parse_improvement_content(response.content)


def _write_iteration_report(output_dir: Path, run: JennyBenchmarkRun, iteration: int) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"iteration-{iteration:02d}-{run.benchmark_id}.md"
    report_path.write_text(generate_markdown_report(run))
    return str(report_path)


async def run_honing_loop(
    *,
    models: list[str],
    case_ids: list[str],
    runs_per_case: int,
    project_id: str,
    working_root: Path,
    output_dir: Path,
    seed: int,
    timeout_seconds: float,
    client_id: str | None,
    use_memory: bool,
    max_iterations: int,
    base_url: str,
    output_json_path: Path | None = None,
    suite_id: str | None = None,
    agent_slug: str = "persona",
    persist_results: bool = True,
) -> dict[str, Any]:
    """Run benchmark/improve cycles until honed or the iteration cap is hit."""
    resolved_client_id = await _resolve_client_id(client_id, project_id)
    iterations: list[JennyHoningIteration] = []
    previous_best_score: float | None = None
    previous_failing_attempts: int | None = None
    previous_clusters: list[dict[str, Any]] | None = None

    async with AsyncAgentHubClient(
        base_url=base_url,
        client_name="jenny-honing-loop",
        client_id=resolved_client_id,
        request_source="backend/scripts/run_jenny_honing_loop.py",
        cli_command="run_jenny_honing_loop",
    ) as client:
        for iteration in range(1, max_iterations + 1):
            benchmark_run = await run_benchmark(
                models=models,
                case_ids=case_ids,
                runs_per_case=runs_per_case,
                project_id=project_id,
                working_root=working_root,
                seed=seed + iteration - 1,
                timeout_seconds=timeout_seconds,
                keep_workdirs=False,
                base_url=base_url,
                client_id=resolved_client_id,
                use_memory=use_memory,
                memory_group_id=f"benchmark:honing:{uuid.uuid4().hex[:8]}",
            )
            report_path = _write_iteration_report(output_dir, benchmark_run, iteration)
            config_snapshot = await capture_benchmark_config_snapshot(agent_slug)
            top_summary = benchmark_run.summaries[0] if benchmark_run.summaries else None
            failing_attempts = sum(1 for attempt in benchmark_run.attempts if not attempt.passed)
            failure_clusters = _group_failures(benchmark_run.attempts)
            persistent_clusters, _, _ = _diff_failure_clusters(previous_clusters, failure_clusters)
            record = JennyHoningIteration(
                iteration=iteration,
                benchmark_id=benchmark_run.benchmark_id,
                top_model=top_summary.model_id if top_summary else None,
                top_score=top_summary.avg_composite_score if top_summary else 0.0,
                failing_attempts=failing_attempts,
                benchmark_report_path=report_path,
                failure_clusters=failure_clusters,
                persistent_failure_clusters=persistent_clusters,
            )

            if failing_attempts == 0:
                if persist_results:
                    payload = build_persistence_payload(
                        benchmark_run,
                        agent_slug=agent_slug,
                        suite_id=suite_id or derive_suite_id(case_ids),
                        run_kind="honing_iteration",
                        use_memory=use_memory,
                        seed=seed + iteration - 1,
                        config_snapshot=config_snapshot,
                        metadata={
                            "iteration": iteration,
                            "benchmark_report_path": report_path,
                            "failure_clusters": failure_clusters,
                            "persistent_failure_clusters": persistent_clusters,
                            "improvement": None,
                        },
                    )
                    record.persisted_run_id = await persist_benchmark_payload(payload)
                iterations.append(record)
                if output_json_path:
                    output_json_path.parent.mkdir(parents=True, exist_ok=True)
                    output_json_path.write_text(json.dumps({
                        "iterations": [item.to_dict() for item in iterations],
                        "completed_iterations": len(iterations),
                        "honed": True,
                    }, indent=2))
                break

            if (
                previous_best_score is not None
                and previous_failing_attempts is not None
                and record.top_score <= previous_best_score
                and failing_attempts >= previous_failing_attempts
            ):
                if persist_results:
                    payload = build_persistence_payload(
                        benchmark_run,
                        agent_slug=agent_slug,
                        suite_id=suite_id or derive_suite_id(case_ids),
                        run_kind="honing_iteration",
                        use_memory=use_memory,
                        seed=seed + iteration - 1,
                        config_snapshot=config_snapshot,
                        metadata={
                            "iteration": iteration,
                            "benchmark_report_path": report_path,
                            "failure_clusters": failure_clusters,
                            "persistent_failure_clusters": persistent_clusters,
                            "stop_reason": "no_improvement",
                            "improvement": None,
                        },
                    )
                    record.persisted_run_id = await persist_benchmark_payload(payload)
                iterations.append(record)
                if output_json_path:
                    output_json_path.parent.mkdir(parents=True, exist_ok=True)
                    output_json_path.write_text(json.dumps({
                        "iterations": [item.to_dict() for item in iterations],
                        "completed_iterations": len(iterations),
                        "honed": False,
                    }, indent=2))
                break

            session_id, content, tools, parsed = await _run_improvement_pass(
                client=client,
                project_id=project_id,
                iteration=iteration,
                run=benchmark_run,
                previous_clusters=previous_clusters,
                timeout_seconds=timeout_seconds,
            )
            record.improvement_session_id = session_id
            record.improvement_content = content
            record.improvement_tools = tools
            record.improvement_parsed = parsed
            if persist_results:
                payload = build_persistence_payload(
                    benchmark_run,
                    agent_slug=agent_slug,
                    suite_id=suite_id or derive_suite_id(case_ids),
                    run_kind="honing_iteration",
                    use_memory=use_memory,
                    seed=seed + iteration - 1,
                    config_snapshot=config_snapshot,
                    metadata={
                        "iteration": iteration,
                        "benchmark_report_path": report_path,
                        "failure_clusters": failure_clusters,
                        "persistent_failure_clusters": persistent_clusters,
                        "improvement": {
                            "session_id": session_id,
                            "tools": tools,
                            "parsed": parsed,
                            "raw_content": content,
                        },
                    },
                )
                record.persisted_run_id = await persist_benchmark_payload(payload)
            iterations.append(record)
            previous_best_score = record.top_score
            previous_failing_attempts = failing_attempts
            previous_clusters = failure_clusters

            if output_json_path:
                output_json_path.parent.mkdir(parents=True, exist_ok=True)
                output_json_path.write_text(json.dumps({
                    "iterations": [item.to_dict() for item in iterations],
                    "completed_iterations": len(iterations),
                    "honed": False,
                }, indent=2))

    return {
        "iterations": [record.to_dict() for record in iterations],
        "completed_iterations": len(iterations),
        "honed": bool(iterations and iterations[-1].failing_attempts == 0),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run iterative Jenny benchmark + self-honing passes")
    parser.add_argument("--models", help="Comma-separated model ids to test")
    parser.add_argument("--cases", help="Comma-separated benchmark case ids to run")
    parser.add_argument("--runs-per-case", type=int, default=1, help="Runs per model per case")
    parser.add_argument("--project-id", default="agent-hub", help="Project id for sessions")
    parser.add_argument(
        "--working-root",
        default=str(ROOT / "backend" / ".tmp" / "jenny-honing-loop"),
        help="Root directory for temporary benchmark workspaces",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "backend" / ".tmp" / "jenny-honing-loop" / "reports"),
        help="Directory for per-iteration reports",
    )
    parser.add_argument("--seed", type=int, default=42, help="Shuffle seed")
    parser.add_argument("--timeout-seconds", type=float, default=180.0, help="Per-turn timeout")
    parser.add_argument("--base-url", default="http://localhost:8003", help="Agent Hub base URL")
    parser.add_argument("--client-id", help="Registered Agent Hub client id")
    parser.add_argument("--max-iterations", type=int, default=2, help="Maximum benchmark/improve cycles")
    parser.add_argument("--use-memory", action="store_true", help="Enable Jenny memory injection")
    parser.add_argument("--output-json", help="Write final loop result to this path")
    parser.add_argument("--suite-id", help="Stable suite identifier for trend/history grouping")
    parser.add_argument("--agent-slug", default="persona", help="Agent slug to attribute benchmark history to")
    parser.add_argument("--no-persist", action="store_true", help="Skip saving iterations to the benchmark history tables")
    args = parser.parse_args()

    models = _parse_csv(args.models, DEFAULT_JENNY_BENCHMARK_MODELS)
    all_case_ids = [case.case_id for case in get_jenny_benchmark_cases()]
    case_ids = _parse_csv(args.cases, all_case_ids)

    result = await run_honing_loop(
        models=models,
        case_ids=case_ids,
        runs_per_case=args.runs_per_case,
        project_id=args.project_id,
        working_root=Path(args.working_root),
        output_dir=Path(args.output_dir),
        seed=args.seed,
        timeout_seconds=args.timeout_seconds,
        client_id=args.client_id,
        use_memory=args.use_memory,
        max_iterations=args.max_iterations,
        base_url=args.base_url,
        output_json_path=Path(args.output_json) if args.output_json else None,
        suite_id=args.suite_id,
        agent_slug=args.agent_slug,
        persist_results=not args.no_persist,
    )

    rendered = json.dumps(result, indent=2)
    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(rendered)
    print(rendered)


if __name__ == "__main__":
    asyncio.run(main())
