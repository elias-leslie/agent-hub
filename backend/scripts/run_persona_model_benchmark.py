#!/usr/bin/env python3
"""Run live persona benchmark cases across multiple candidate models."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = ROOT / "backend" / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"

if (
    VENV_PYTHON.exists()
    and Path(sys.prefix).resolve() != VENV_DIR.resolve()
    and os.environ.get("PERSONA_BENCHMARK_NO_REEXEC") != "1"
):
    os.environ["PERSONA_BENCHMARK_NO_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "packages" / "agent-hub-client"))

from agent_hub import AsyncAgentHubClient

from scripts.persona_benchmark_cases import (
    DEFAULT_PERSONA_BENCHMARK_MODELS,
    get_case_by_id,
    get_persona_benchmark_cases,
    suggest_suite_id,
)
from scripts.persona_benchmark_eval import PersonaBenchmarkRun, summarize_attempts
from scripts.persona_benchmark_persistence import (
    _persist_run,
)
from scripts.persona_benchmark_report import generate_markdown_report
from scripts.persona_benchmark_runner import _execute_attempt_loop, _resolve_client_id
from scripts.persona_display import load_persona_display_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_AGENT_SLUG = "persona"
_BENCHMARK_ID_PREFIX = "persona-benchmark"
_CLIENT_NAME = "persona-model-benchmark"
_REQUEST_SOURCE = "backend/scripts/run_persona_model_benchmark.py"
_CLI_COMMAND = "run_persona_model_benchmark"
_MEMORY_GROUP_PREFIX = "benchmark:"
_DEFAULT_BASE_URL = "http://localhost:8003"
_DEFAULT_PROJECT_ID = "agent-hub"
_SUITE_ID_PREFIX = "benchmark-suite-"
_DEFAULT_WORKING_ROOT = str(ROOT / "backend" / ".tmp" / "persona-model-benchmark")
_DEFAULT_TASK_TYPE = "wake"


# ---------------------------------------------------------------------------
# Orchestration helpers
# ---------------------------------------------------------------------------

def _parse_csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def derive_suite_id(case_ids: list[str]) -> str:
    """Build a stable suite identifier for a benchmark battery."""
    normalized = sorted(set(case_ids))
    if len(normalized) == 1:
        return normalized[0]
    if family_suite_id := suggest_suite_id(normalized):
        return family_suite_id
    digest = hashlib.sha256(",".join(normalized).encode("utf-8")).hexdigest()[:8]
    return f"{_SUITE_ID_PREFIX}{digest}"


def _build_attempt_order(
    models: list[str],
    case_ids: list[str],
    runs_per_case: int,
    seed: int,
) -> list[tuple[str, str, int]]:
    items = [
        (model_id, case_id, run_number)
        for run_number in range(1, runs_per_case + 1)
        for model_id in models
        for case_id in case_ids
    ]
    random.Random(seed).shuffle(items)
    return items


def _validate_case_project_requirements(case_ids: list[str], project_id: str) -> None:
    """Ensure selected cases are compatible with the requested project context."""
    incompatible_cases = [
        case.case_id
        for case in (get_case_by_id(case_id) for case_id in case_ids)
        if case.required_project_id and case.required_project_id != project_id
    ]
    if incompatible_cases:
        raise ValueError(
            "Selected cases require a different --project-id. "
            f"project_id={project_id!r}, incompatible_cases={incompatible_cases}"
        )


async def run_benchmark(
    *,
    models: list[str],
    case_ids: list[str],
    runs_per_case: int,
    project_id: str,
    working_root: Path,
    seed: int,
    timeout_seconds: float | None,
    keep_workdirs: bool,
    base_url: str,
    client_id: str | None,
    use_memory: bool,
    memory_group_id: str | None,
    memory_variant_override: str | None = None,
    task_type: str = _DEFAULT_TASK_TYPE,
) -> PersonaBenchmarkRun:
    benchmark_id = f"{_BENCHMARK_ID_PREFIX}-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(UTC).isoformat()
    _validate_case_project_requirements(case_ids, project_id)
    order = _build_attempt_order(models, case_ids, runs_per_case, seed)
    resolved_client_id = await _resolve_client_id(client_id, project_id)
    resolved_memory_group_id = memory_group_id or f"{_MEMORY_GROUP_PREFIX}{benchmark_id}"
    persona_name = await load_persona_display_name()

    async with AsyncAgentHubClient(
        base_url=base_url,
        client_name=_CLIENT_NAME,
        client_id=resolved_client_id,
        request_source=_REQUEST_SOURCE,
        cli_command=_CLI_COMMAND,
    ) as client:
        attempts = await _execute_attempt_loop(
            client, order, benchmark_id=benchmark_id, project_id=project_id,
            working_root=working_root, timeout_seconds=timeout_seconds,
            keep_workdirs=keep_workdirs, use_memory=use_memory,
            memory_group_id=resolved_memory_group_id,
            memory_variant_override=memory_variant_override,
            task_type=task_type,
            persona_name=persona_name,
        )

    completed_at = datetime.now(UTC).isoformat()
    summaries = summarize_attempts(attempts)
    return PersonaBenchmarkRun(
        benchmark_id=benchmark_id, project_id=project_id, models=models,
        case_ids=case_ids, runs_per_case=runs_per_case,
        started_at=started_at, completed_at=completed_at,
        attempts=attempts, summaries=summaries,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_dry_run(models: list[str], case_ids: list[str], runs_per_case: int, seed: int) -> None:
    print("Persona model benchmark dry run")
    print("")
    print("Models:")
    for model in models:
        print(f"  - {model}")
    print("")
    print("Cases:")
    for case_id in case_ids:
        case = get_case_by_id(case_id)
        print(f"  - {case.case_id}: {case.name}")
    print("")
    print(f"Runs per case: {runs_per_case}")
    print(f"Seed: {seed}")
    print(f"Total attempts: {len(models) * len(case_ids) * runs_per_case}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run persona benchmark cases across model candidates")
    parser.add_argument("--agent-slug", default=_AGENT_SLUG, help="Agent slug to attribute benchmark history to")
    parser.add_argument("--models", help="Comma-separated model ids to test")
    parser.add_argument("--cases", help="Comma-separated benchmark case ids to run")
    parser.add_argument("--suite-id", help="Stable suite identifier for trend/history grouping")
    parser.add_argument("--runs-per-case", type=int, default=3, help="Runs per model per case")
    parser.add_argument("--project-id", default=_DEFAULT_PROJECT_ID, help="Project id for benchmark sessions")
    parser.add_argument("--working-root", default=_DEFAULT_WORKING_ROOT, help="Root directory for temporary benchmark workspaces")
    parser.add_argument("--seed", type=int, default=42, help="Shuffle seed for attempt order")
    parser.add_argument("--timeout-seconds", type=float, default=None, help="Optional client HTTP timeout ceiling for each completion request.")
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL, help="Agent Hub base URL")
    parser.add_argument("--client-id", help="Registered Agent Hub client id for access control")
    parser.add_argument("--output-json", help="Write full JSON result to this path")
    parser.add_argument("--output-md", help="Write markdown report to this path")
    parser.add_argument("--keep-workdirs", action="store_true", help="Keep temporary workspaces")
    parser.add_argument("--use-memory", action="store_true", help="Enable persona memory injection for full-context benchmark runs")
    parser.add_argument("--memory-group-id", help="Explicit memory group id to use when memory injection is enabled")
    parser.add_argument("--memory-variant-override", choices=("BASELINE", "ENHANCED", "MINIMAL", "AGGRESSIVE"), help="Override the memory injection variant for controlled benchmark experiments")
    parser.add_argument("--task-type", default=_DEFAULT_TASK_TYPE, choices=("wake", "heartbeat"), help="Agent task type to benchmark; use heartbeat to include live heartbeat instructions in context")
    parser.add_argument("--experiment-key", help="Stable experiment id for repeated baseline/candidate comparisons")
    parser.add_argument("--experiment-name", help="Display name for the benchmark experiment")
    parser.add_argument("--experiment-cohort", choices=("baseline", "candidate"), help="Cohort label for this persisted run")
    parser.add_argument("--experiment-hypothesis", help="Short hypothesis being tested")
    parser.add_argument("--min-runs-per-cohort", type=int, default=3, help="Minimum repeated runs required before experiment decisions can promote or rollback")
    parser.add_argument("--promote-on-win", action="store_true", help="When the candidate cohort wins an experiment, promote its memory variant to production")
    parser.add_argument("--no-persist", action="store_true", help="Skip saving results to the benchmark history tables")
    parser.add_argument("--dry-run", action="store_true", help="Print roster and exit")
    return parser


def _write_outputs(
    run: PersonaBenchmarkRun,
    args: argparse.Namespace,
    suite_id: str,
    persisted_run_id: str | None,
    report: str,
) -> None:
    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps({**run.to_dict(), "persisted_run_id": persisted_run_id, "suite_id": suite_id}, indent=2))
        logger.info("JSON results written to %s", args.output_json)
    if args.output_md:
        output_md = Path(args.output_md)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(report)
        logger.info("Markdown report written to %s", args.output_md)
    if not args.output_md:
        print(report)


async def main() -> None:
    args = _build_parser().parse_args()
    models = _parse_csv(args.models, DEFAULT_PERSONA_BENCHMARK_MODELS)
    case_ids = _parse_csv(args.cases, [case.case_id for case in get_persona_benchmark_cases()])

    if args.dry_run:
        _print_dry_run(models, case_ids, args.runs_per_case, args.seed)
        return

    run = await run_benchmark(
        models=models, case_ids=case_ids, runs_per_case=args.runs_per_case,
        project_id=args.project_id, working_root=Path(args.working_root),
        seed=args.seed, timeout_seconds=args.timeout_seconds,
        keep_workdirs=args.keep_workdirs, base_url=args.base_url,
        client_id=args.client_id, use_memory=args.use_memory,
        memory_group_id=args.memory_group_id,
        memory_variant_override=args.memory_variant_override,
        task_type=args.task_type,
    )
    suite_id = args.suite_id or derive_suite_id(case_ids)
    report = generate_markdown_report(run, persona_name=await load_persona_display_name())
    persisted_run_id: str | None = None
    if not args.no_persist:
        persisted_run_id = await _persist_run(run, args, suite_id)
    _write_outputs(run, args, suite_id, persisted_run_id, report)


if __name__ == "__main__":
    asyncio.run(main())
