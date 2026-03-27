#!/usr/bin/env python3
"""Run live helper-agent output contract benchmark cases."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
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
    and os.environ.get("AGENT_OUTPUT_BENCHMARK_NO_REEXEC") != "1"
):
    os.environ["AGENT_OUTPUT_BENCHMARK_NO_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "packages" / "agent-hub-client"))

from agent_hub import AsyncAgentHubClient

from app.db import async_session
from app.models.field_lengths import EXTERNAL_ID_MAX_LENGTH
from app.services.agent_benchmark_service import (
    capture_benchmark_config_snapshot,
    get_benchmark_experiment_summary_by_key,
    persist_benchmark_payload,
)
from app.services.benchmark_aggregation import aggregate_attempts, merge_efficiency_metadata
from scripts.agent_output_benchmark_cases import (
    get_agent_output_benchmark_cases,
    get_default_case_ids,
)
from scripts.agent_output_benchmark_eval import (
    AgentOutputBenchmarkRun,
    summarize_output_contract_attempts,
)
from scripts.agent_output_benchmark_runner import (
    CLI_COMMAND,
    CLIENT_NAME,
    REQUEST_SOURCE,
    TASK_TYPE,
    collect_all_attempts,
)
from scripts.persona_benchmark_runner import _resolve_client_id
from scripts.run_persona_model_benchmark import _parse_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUITE_ID_PREFIX = "output-contract"
RUN_KIND = "output_contract_benchmark"
BENCHMARK_ID_PREFIX = "output-contract"
PRIMARY_ACTION = "output_contract"
DEFAULT_PROJECT_ID = "agent-hub"
DEFAULT_BASE_URL = "http://localhost:8003"
DEFAULT_SEED = 42
DEFAULT_RUNS_PER_CASE = 1
DEFAULT_MIN_RUNS_PER_COHORT = 3


# ---------------------------------------------------------------------------
# Suite / external-id helpers
# ---------------------------------------------------------------------------

def derive_suite_id(agent_slug: str, case_ids: list[str]) -> str:
    """Build a stable suite identifier for one helper agent's output contract."""
    defaults = sorted(get_default_case_ids(agent_slug))
    normalized = sorted(set(case_ids))
    if normalized == defaults:
        return f"{SUITE_ID_PREFIX}-{agent_slug}"
    if len(normalized) == 1:
        return normalized[0]
    return f"{SUITE_ID_PREFIX}-{agent_slug}-custom"


def _build_benchmark_external_id(agent_slug: str, case_id: str, run_number: int) -> str:
    """Build a stable benchmark correlation id that fits the session persistence limit."""
    case_fragment = case_id.replace("_summary_tag_override", "").replace("_", "-")[:60]
    digest = hashlib.sha1(f"{agent_slug}:{case_id}:{run_number}".encode()).hexdigest()[:8]
    external_id = f"benchmark:{case_fragment}:{run_number}:{digest}"
    return external_id[:EXTERNAL_ID_MAX_LENGTH]


# ---------------------------------------------------------------------------
# Benchmark run
# ---------------------------------------------------------------------------

async def run_agent_output_benchmark(
    *,
    agent_slug: str,
    models: list[str] | None,
    case_ids: list[str],
    runs_per_case: int,
    project_id: str,
    seed: int,
    timeout_seconds: float | None,
    base_url: str,
    client_id: str | None,
    use_memory: bool,
    memory_group_id: str | None = None,
) -> AgentOutputBenchmarkRun:
    started_at = datetime.now(UTC).isoformat()
    benchmark_id = f"{BENCHMARK_ID_PREFIX}-{agent_slug}-{uuid.uuid4().hex[:8]}"
    client_id_resolved = await _resolve_client_id(client_id, project_id)
    agent_snapshot = await capture_benchmark_config_snapshot(agent_slug, task_type=TASK_TYPE)
    if not agent_snapshot:
        raise ValueError(f"Active agent '{agent_slug}' not found")

    if models:
        requested_models = list(models)
    else:
        primary_model = str(agent_snapshot.get("primary_model_id") or "").strip()
        if not primary_model:
            raise ValueError(f"Could not resolve primary model for agent '{agent_slug}'")
        requested_models = [primary_model]

    async with AsyncAgentHubClient(
        base_url=base_url, client_name=CLIENT_NAME, client_id=client_id_resolved,
        request_source=REQUEST_SOURCE, cli_command=CLI_COMMAND,
    ) as client:
        attempts = await collect_all_attempts(
            client=client, benchmark_id=benchmark_id, project_id=project_id,
            agent_slug=agent_slug, requested_models=requested_models,
            explicit_model_override=bool(models), case_ids=case_ids,
            runs_per_case=runs_per_case, timeout_seconds=timeout_seconds,
            use_memory=use_memory, seed=seed, memory_group_id=memory_group_id,
            build_external_id=_build_benchmark_external_id,
        )

    resolved_models = sorted({a.requested_model or a.effective_model or a.model_id for a in attempts})
    return AgentOutputBenchmarkRun(
        benchmark_id=benchmark_id, project_id=project_id, agent_slug=agent_slug,
        models=resolved_models, case_ids=case_ids, runs_per_case=runs_per_case,
        started_at=started_at, completed_at=datetime.now(UTC).isoformat(),
        attempts=attempts, summaries=summarize_output_contract_attempts(attempts),
    )


# ---------------------------------------------------------------------------
# Persistence payload
# ---------------------------------------------------------------------------

def build_persistence_payload(
    run: AgentOutputBenchmarkRun,
    *,
    suite_id: str,
    run_kind: str,
    use_memory: bool,
    seed: int | None,
    config_snapshot: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    experiment: dict[str, object] | None = None,
) -> dict[str, object]:
    attempts = [a.to_dict() for a in run.attempts]
    aggregate = aggregate_attempts(run.attempts)
    normalized = [
        {**a, "primary_action": PRIMARY_ACTION, "should_dispatch": None, "should_close": None,
         "confidence": None, "summary": a.get("summary_excerpt"), "raw_content": a.get("content", "")}
        for a in attempts
    ]
    return {
        "benchmark_id": run.benchmark_id, "agent_slug": run.agent_slug, "project_id": run.project_id,
        "suite_id": suite_id, "run_kind": run_kind, "status": "completed",
        "models": list(run.models), "case_ids": list(run.case_ids), "runs_per_case": run.runs_per_case,
        "use_memory": use_memory, "seed": seed,
        "avg_score": aggregate.avg_score, "pass_rate": aggregate.pass_rate,
        "attempt_count": aggregate.total_attempts, "passed_attempt_count": aggregate.passed_attempt_count,
        "infra_failure_count": aggregate.infra_failure_count,
        "config_snapshot": dict(config_snapshot or {}),
        "metadata": merge_efficiency_metadata(metadata, aggregate),
        "experiment": dict(experiment) if experiment else None,
        "started_at": run.started_at, "completed_at": run.completed_at, "attempts": normalized,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run helper-agent output contract benchmark")
    parser.add_argument("--agent-slug", required=True)
    parser.add_argument("--models", help="Comma-separated model ids to override the agent default")
    parser.add_argument("--cases", help="Comma-separated benchmark case ids to run")
    parser.add_argument("--runs-per-case", type=int, default=DEFAULT_RUNS_PER_CASE)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--timeout-seconds", type=float, default=None,
                        help="Optional client HTTP timeout ceiling for each completion request.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--client-id")
    parser.add_argument("--use-memory", action="store_true")
    parser.add_argument("--suite-id")
    parser.add_argument("--output-json")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--experiment-key")
    parser.add_argument("--experiment-name")
    parser.add_argument("--experiment-hypothesis")
    parser.add_argument("--experiment-cohort", choices=["baseline", "candidate"])
    parser.add_argument("--min-runs-per-cohort", type=int, default=DEFAULT_MIN_RUNS_PER_COHORT)
    return parser


async def _persist_run(
    run: AgentOutputBenchmarkRun, args: argparse.Namespace, case_ids: list[str],
) -> tuple[str | None, dict[str, object] | None]:
    config_snapshot = await capture_benchmark_config_snapshot(args.agent_slug, task_type=TASK_TYPE)
    suite_id = args.suite_id or derive_suite_id(args.agent_slug, case_ids)
    experiment_payload: dict[str, object] | None = None
    if args.experiment_key:
        if not args.experiment_cohort:
            raise ValueError("--experiment-cohort is required when --experiment-key is set")
        experiment_payload = {
            "experiment_key": args.experiment_key, "name": args.experiment_name or args.experiment_key,
            "cohort": args.experiment_cohort, "hypothesis": args.experiment_hypothesis,
            "suite_id": suite_id, "project_id": args.project_id,
            "min_runs_per_cohort": args.min_runs_per_cohort,
        }
    payload = build_persistence_payload(
        run, suite_id=suite_id, run_kind=RUN_KIND, use_memory=args.use_memory, seed=args.seed,
        config_snapshot=config_snapshot,
        metadata={"benchmark_type": PRIMARY_ACTION, "benchmark_agent_slug": args.agent_slug},
        experiment=experiment_payload,
    )
    persisted_run_id = await persist_benchmark_payload(payload)
    experiment_summary: dict[str, object] | None = None
    if args.experiment_key:
        async with async_session() as db:
            experiment_summary = await get_benchmark_experiment_summary_by_key(db, args.experiment_key)
    return persisted_run_id, experiment_summary


async def main() -> None:
    args = _build_arg_parser().parse_args()
    get_agent_output_benchmark_cases(args.agent_slug)
    models = _parse_csv(args.models, [])
    case_ids = _parse_csv(args.cases, get_default_case_ids(args.agent_slug))
    run = await run_agent_output_benchmark(
        agent_slug=args.agent_slug, models=models or None, case_ids=case_ids,
        runs_per_case=args.runs_per_case, project_id=args.project_id, seed=args.seed,
        timeout_seconds=args.timeout_seconds, base_url=args.base_url,
        client_id=args.client_id, use_memory=args.use_memory,
    )
    persisted_run_id: str | None = None
    experiment_summary: dict[str, object] | None = None
    if not args.no_persist:
        persisted_run_id, experiment_summary = await _persist_run(run, args, case_ids)
    output = {
        **run.to_dict(), "persisted_run_id": persisted_run_id,
        "suite_id": args.suite_id or derive_suite_id(args.agent_slug, case_ids),
        "experiment_summary": experiment_summary,
    }
    rendered = json.dumps(output, indent=2)
    if args.output_json:
        out = Path(args.output_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered)
    print(rendered)


if __name__ == "__main__":
    asyncio.run(main())
