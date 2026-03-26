#!/usr/bin/env python3
"""Run iterative persona benchmark passes and prompt the persona to self-correct between runs."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = ROOT / "backend" / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
DEFAULT_WORKING_ROOT = ROOT / "backend" / ".tmp" / "persona-honing-loop"
DEFAULT_OUTPUT_DIR = DEFAULT_WORKING_ROOT / "reports"

if (
    VENV_PYTHON.exists()
    and Path(sys.prefix).resolve() != VENV_DIR.resolve()
    and os.environ.get("PERSONA_HONING_NO_REEXEC") != "1"
):
    os.environ["PERSONA_HONING_NO_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "packages" / "agent-hub-client"))

from agent_hub import AsyncAgentHubClient

from scripts.completion_review_benchmark_cases import (
    DEFAULT_COMPLETION_REVIEW_MODELS,
    get_default_completion_review_case_ids,
)
from scripts.persona_benchmark_cases import (
    DEFAULT_PERSONA_BENCHMARK_MODELS,
    get_persona_benchmark_cases,
)
from scripts.persona_honing._constants import (
    CLI_COMMAND,
    CLIENT_NAME,
    DEFAULT_AGENT_SLUG,
    DEFAULT_BASE_URL,
    DEFAULT_BENCHMARK_TASK_TYPE,
    DEFAULT_COHORT_REPETITIONS,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_PROJECT_ID,
    DEFAULT_RUNS_PER_CASE,
    DEFAULT_SEED,
    DEFAULT_TIMEOUT_SECONDS,
    REQUEST_SOURCE,
)
from scripts.persona_honing._experiment import (  # noqa: F401
    _run_improvement_pass,
    _run_iteration,
)
from scripts.persona_honing._models import _IterationConfig, _LoopState
from scripts.persona_honing._prompt import build_honing_prompt  # noqa: F401 (re-export)
from scripts.run_persona_model_benchmark import _parse_csv, _resolve_client_id

LoopResult = dict[str, Any]


class HoningLoopParser(argparse.ArgumentParser):
    def __init__(self) -> None:
        super().__init__(description="Run iterative persona benchmark + self-honing passes")
        self._add_arguments()

    def _add_arguments(self) -> None:
        self.add_argument("--models", help="Comma-separated model ids to test")
        self.add_argument("--cases", help="Comma-separated benchmark case ids to run")
        self.add_argument("--runs-per-case", type=int, default=DEFAULT_RUNS_PER_CASE)
        self.add_argument("--reviewer-models", help="Comma-separated reviewer model ids to test")
        self.add_argument("--reviewer-cases", help="Comma-separated completion-review case ids to run")
        self.add_argument("--reviewer-runs-per-case", type=int, default=DEFAULT_RUNS_PER_CASE)
        self.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
        self.add_argument("--working-root", default=str(DEFAULT_WORKING_ROOT))
        self.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
        self.add_argument("--seed", type=int, default=DEFAULT_SEED)
        self.add_argument(
            "--timeout-seconds",
            type=float,
            default=DEFAULT_TIMEOUT_SECONDS,
            help="Optional client HTTP timeout ceiling for each completion request.",
        )
        self.add_argument("--base-url", default=DEFAULT_BASE_URL)
        self.add_argument("--client-id")
        self.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
        self.add_argument("--cohort-repetitions", type=int, default=DEFAULT_COHORT_REPETITIONS)
        self.add_argument("--use-memory", action="store_true")
        self.add_argument(
            "--benchmark-task-type",
            default=DEFAULT_BENCHMARK_TASK_TYPE,
            choices=("wake", "heartbeat"),
        )
        self.add_argument("--output-json")
        self.add_argument("--suite-id")
        self.add_argument("--agent-slug", default=DEFAULT_AGENT_SLUG)
        self.add_argument("--no-persist", action="store_true")
        self.add_argument("--disable-completion-review", action="store_true")


def _flush_output_json(path: Path, loop_state: _LoopState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(loop_state.to_result(), indent=2))


def _build_client(base_url: str, resolved_client_id: str) -> AsyncAgentHubClient:
    return AsyncAgentHubClient(
        base_url=base_url,
        client_name=CLIENT_NAME,
        client_id=resolved_client_id,
        request_source=REQUEST_SOURCE,
        cli_command=CLI_COMMAND,
    )


async def _run_iterations(
    *,
    client: AsyncAgentHubClient,
    loop_state: _LoopState,
    max_iterations: int,
    output_json_path: Path | None,
    suite_id: str | None,
    iteration_kwargs: _IterationConfig,
) -> None:
    for iteration in range(1, max_iterations + 1):
        should_stop = await _run_iteration(
            iteration=iteration,
            loop_state=loop_state,
            client=client,
            suite_id=suite_id,
            cfg=iteration_kwargs,
        )
        if output_json_path:
            _flush_output_json(output_json_path, loop_state)
        if should_stop:
            return


async def run_honing_loop(
    *,
    models: list[str],
    case_ids: list[str],
    runs_per_case: int,
    project_id: str,
    working_root: Path,
    output_dir: Path,
    seed: int,
    timeout_seconds: float | None,
    client_id: str | None,
    use_memory: bool,
    benchmark_task_type: str,
    max_iterations: int,
    cohort_repetitions: int,
    base_url: str,
    output_json_path: Path | None = None,
    suite_id: str | None = None,
    agent_slug: str = DEFAULT_AGENT_SLUG,
    persist_results: bool = True,
    disable_completion_review: bool = False,
    reviewer_models: list[str] | None = None,
    reviewer_case_ids: list[str] | None = None,
    reviewer_runs_per_case: int = DEFAULT_RUNS_PER_CASE,
) -> LoopResult:
    """Run benchmark/improve cycles until honed or the iteration cap is hit."""
    resolved_client_id = await _resolve_client_id(client_id, project_id)
    loop_state = _LoopState()
    iteration_kwargs: _IterationConfig = {
        "models": models, "case_ids": case_ids, "runs_per_case": runs_per_case,
        "reviewer_models": reviewer_models, "reviewer_case_ids": reviewer_case_ids,
        "reviewer_runs_per_case": reviewer_runs_per_case,
        "project_id": project_id, "working_root": working_root, "output_dir": output_dir,
        "seed": seed, "timeout_seconds": timeout_seconds, "client_id": resolved_client_id,
        "use_memory": use_memory, "benchmark_task_type": benchmark_task_type,
        "cohort_repetitions": cohort_repetitions, "base_url": base_url, "agent_slug": agent_slug,
        "persist_results": persist_results, "disable_completion_review": disable_completion_review,
    }
    async with _build_client(base_url, resolved_client_id) as client:
        await _run_iterations(
            client=client,
            loop_state=loop_state,
            max_iterations=max_iterations,
            output_json_path=output_json_path,
            suite_id=suite_id,
            iteration_kwargs=iteration_kwargs,
        )
    return loop_state.to_result()


def _parse_case_ids(cases_csv: str | None) -> list[str]:
    all_case_ids = [case.case_id for case in get_persona_benchmark_cases()]
    return _parse_csv(cases_csv, all_case_ids)


def _parse_reviewer_case_ids(cases_csv: str | None) -> list[str]:
    return _parse_csv(cases_csv, get_default_completion_review_case_ids())


def _result_output_path(output_json: str | None) -> Path | None:
    return Path(output_json) if output_json else None


async def _run_from_args(args: argparse.Namespace) -> LoopResult:
    return await run_honing_loop(
        models=_parse_csv(args.models, DEFAULT_PERSONA_BENCHMARK_MODELS),
        case_ids=_parse_case_ids(args.cases),
        runs_per_case=args.runs_per_case,
        reviewer_models=_parse_csv(args.reviewer_models, DEFAULT_COMPLETION_REVIEW_MODELS),
        reviewer_case_ids=_parse_reviewer_case_ids(args.reviewer_cases),
        reviewer_runs_per_case=args.reviewer_runs_per_case,
        project_id=args.project_id,
        working_root=Path(args.working_root),
        output_dir=Path(args.output_dir),
        seed=args.seed,
        timeout_seconds=args.timeout_seconds,
        client_id=args.client_id,
        use_memory=args.use_memory,
        benchmark_task_type=args.benchmark_task_type,
        max_iterations=args.max_iterations,
        cohort_repetitions=args.cohort_repetitions,
        base_url=args.base_url,
        output_json_path=_result_output_path(args.output_json),
        suite_id=args.suite_id,
        agent_slug=args.agent_slug,
        persist_results=not args.no_persist,
        disable_completion_review=args.disable_completion_review,
    )


def _write_result(path: Path, rendered: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered)


async def main() -> None:
    args = HoningLoopParser().parse_args()
    result = await _run_from_args(args)
    rendered = json.dumps(result, indent=2)
    output_path = _result_output_path(args.output_json)
    if output_path:
        _write_result(output_path, rendered)
    print(rendered)


if __name__ == "__main__":
    asyncio.run(main())
