#!/usr/bin/env python3
"""Run live completion-review benchmark cases across candidate reviewer models."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_DIR = ROOT / "backend" / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"

if (
    VENV_PYTHON.exists()
    and Path(sys.prefix).resolve() != VENV_DIR.resolve()
    and os.environ.get("COMPLETION_REVIEW_BENCHMARK_NO_REEXEC") != "1"
):
    os.environ["COMPLETION_REVIEW_BENCHMARK_NO_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "packages" / "agent-hub-client"))

from agent_hub import AsyncAgentHubClient

from app.db import async_session
from app.services.agent_benchmark_service import (
    capture_benchmark_config_snapshot,
    get_benchmark_experiment_summary_by_key,
    persist_benchmark_payload,
)
from app.services.benchmark_aggregation import aggregate_attempts, merge_efficiency_metadata
from scripts.completion_review_benchmark_cases import (
    DEFAULT_COMPLETION_REVIEW_MODELS,
    get_completion_review_case_by_id,
    get_default_completion_review_case_ids,
)
from scripts.completion_review_benchmark_eval import (
    CompletionReviewBenchmarkAttempt,
    CompletionReviewBenchmarkRun,
    score_completion_review_attempt,
    summarize_completion_review_attempts,
)
from scripts.run_persona_model_benchmark import (
    _fetch_used_tool_names,
    _parse_csv,
    _resolve_client_id,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "case_id": {"type": "string"},
        "decision": {"enum": ["complete", "continue", "escalate"]},
        "confidence": {"enum": ["low", "medium", "high"]},
        "reason": {"type": "string"},
        "focus": {"type": "string"},
    },
    "required": ["case_id", "decision", "confidence", "reason", "focus"],
}


def derive_suite_id(case_ids: list[str]) -> str:
    if case_ids == get_default_completion_review_case_ids():
        return "completion-review-reviewer"
    if len(case_ids) == 1:
        return case_ids[0]
    return "completion-review-suite"


async def _run_one_attempt(
    *,
    client: AsyncAgentHubClient,
    benchmark_id: str,
    project_id: str,
    model_id: str,
    case_id: str,
    run_number: int,
    timeout_seconds: float,
    use_memory: bool,
    memory_group_id: str,
) -> CompletionReviewBenchmarkAttempt:
    case = get_completion_review_case_by_id(case_id)
    message_content = f"@{model_id}\n{await case.build_prompt()}"
    started = time.perf_counter()
    try:
        response = await client.complete(
            messages=[{"role": "user", "content": message_content}],
            project_id=project_id,
            agent_slug="supervisor",
            task_type="review",
            external_id=f"completion-review-benchmark:{benchmark_id}:{case.case_id}:run-{run_number}",
            enable_caching=False,
            skip_cache=True,
            use_memory=use_memory,
            memory_group_id=memory_group_id,
            max_turns=1,
            execute_tools=False,
            timeout_seconds=timeout_seconds,
            disable_agent_fallbacks=True,
            response_format={"type": "json_object", "schema": _REVIEW_SCHEMA},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        used_tool_names = await _fetch_used_tool_names(response.session_id)
        return score_completion_review_attempt(
            case=case,
            model_id=model_id,
            run_number=run_number,
            latency_ms=latency_ms,
            content=response.content,
            session_id=response.session_id,
            provider=response.provider,
            effective_model=response.model,
            fallback_used=response.model != model_id,
            turns=response.turns,
            tool_calls_count=response.tool_calls_count,
            used_tool_names=used_tool_names,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.total_tokens,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return score_completion_review_attempt(
            case=case,
            model_id=model_id,
            run_number=run_number,
            latency_ms=latency_ms,
            content="",
            session_id=None,
            provider=None,
            effective_model=None,
            fallback_used=False,
            turns=0,
            tool_calls_count=0,
            used_tool_names=[],
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            failure_detail=str(exc),
        )


async def run_completion_review_benchmark(
    *,
    models: list[str],
    case_ids: list[str],
    runs_per_case: int,
    project_id: str,
    seed: int,
    timeout_seconds: float,
    base_url: str,
    client_id: str | None,
    use_memory: bool,
    memory_group_id: str | None = None,
) -> CompletionReviewBenchmarkRun:
    started_at = datetime.now(UTC).isoformat()
    benchmark_id = f"completion-review-{uuid.uuid4().hex[:8]}"
    client_id_resolved = await _resolve_client_id(client_id, project_id)
    attempts: list[CompletionReviewBenchmarkAttempt] = []

    async with AsyncAgentHubClient(
        base_url=base_url,
        client_name="completion-review-benchmark",
        client_id=client_id_resolved,
        request_source="backend/scripts/run_completion_review_model_benchmark.py",
        cli_command="run_completion_review_model_benchmark",
    ) as client:
        for run_number in range(1, runs_per_case + 1):
            for model_id in models:
                for case_id in case_ids:
                    attempt = await _run_one_attempt(
                        client=client,
                        benchmark_id=benchmark_id,
                        project_id=project_id,
                        model_id=model_id,
                        case_id=case_id,
                        run_number=run_number,
                        timeout_seconds=timeout_seconds,
                        use_memory=use_memory,
                        memory_group_id=memory_group_id or f"completion-review-benchmark:{seed}:{run_number}",
                    )
                    attempts.append(attempt)

    return CompletionReviewBenchmarkRun(
        benchmark_id=benchmark_id,
        project_id=project_id,
        models=models,
        case_ids=case_ids,
        runs_per_case=runs_per_case,
        started_at=started_at,
        completed_at=datetime.now(UTC).isoformat(),
        attempts=attempts,
        summaries=summarize_completion_review_attempts(attempts),
    )


def build_persistence_payload(
    run: CompletionReviewBenchmarkRun,
    *,
    agent_slug: str,
    suite_id: str,
    run_kind: str,
    use_memory: bool,
    seed: int | None,
    config_snapshot: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    experiment: dict[str, object] | None = None,
) -> dict[str, object]:
    attempts = [attempt.to_dict() for attempt in run.attempts]
    aggregate = aggregate_attempts(run.attempts)

    normalized_attempts: list[dict[str, object]] = []
    for attempt in attempts:
        parsed = attempt.get("parsed") if isinstance(attempt.get("parsed"), dict) else {}
        normalized_attempts.append(
            {
                **attempt,
                "primary_action": parsed.get("decision"),
                "should_dispatch": None,
                "should_close": None,
                "confidence": parsed.get("confidence"),
                "summary": parsed.get("reason"),
                "raw_content": attempt.get("content", ""),
            }
        )

    return {
        "benchmark_id": run.benchmark_id,
        "agent_slug": agent_slug,
        "project_id": run.project_id,
        "suite_id": suite_id,
        "run_kind": run_kind,
        "status": "completed",
        "models": list(run.models),
        "case_ids": list(run.case_ids),
        "runs_per_case": run.runs_per_case,
        "use_memory": use_memory,
        "seed": seed,
        "avg_score": aggregate.avg_score,
        "pass_rate": aggregate.pass_rate,
        "attempt_count": aggregate.total_attempts,
        "passed_attempt_count": aggregate.passed_attempt_count,
        "infra_failure_count": aggregate.infra_failure_count,
        "config_snapshot": dict(config_snapshot or {}),
        "metadata": merge_efficiency_metadata(metadata, aggregate),
        "experiment": dict(experiment) if experiment else None,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "attempts": normalized_attempts,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run completion-review model benchmark")
    parser.add_argument("--models", help="Comma-separated model ids to test")
    parser.add_argument("--cases", help="Comma-separated benchmark case ids to run")
    parser.add_argument("--runs-per-case", type=int, default=1)
    parser.add_argument("--project-id", default="persona-sandbox")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--base-url", default="http://localhost:8003")
    parser.add_argument("--client-id")
    parser.add_argument("--use-memory", action="store_true")
    parser.add_argument("--agent-slug", default="persona")
    parser.add_argument("--suite-id")
    parser.add_argument("--output-json")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--experiment-key")
    parser.add_argument("--experiment-name")
    parser.add_argument("--experiment-hypothesis")
    parser.add_argument("--experiment-cohort", choices=["baseline", "candidate"])
    parser.add_argument("--min-runs-per-cohort", type=int, default=3)
    args = parser.parse_args()

    models = _parse_csv(args.models, DEFAULT_COMPLETION_REVIEW_MODELS)
    case_ids = _parse_csv(args.cases, get_default_completion_review_case_ids())
    run = await run_completion_review_benchmark(
        models=models,
        case_ids=case_ids,
        runs_per_case=args.runs_per_case,
        project_id=args.project_id,
        seed=args.seed,
        timeout_seconds=args.timeout_seconds,
        base_url=args.base_url,
        client_id=args.client_id,
        use_memory=args.use_memory,
    )

    persisted_run_id: str | None = None
    experiment_summary: dict[str, object] | None = None
    if not args.no_persist:
        config_snapshot = await capture_benchmark_config_snapshot(
            args.agent_slug,
            task_type="review",
        )
        experiment_payload = None
        if args.experiment_key:
            if not args.experiment_cohort:
                raise ValueError("--experiment-cohort is required when --experiment-key is set")
            experiment_payload = {
                "experiment_key": args.experiment_key,
                "name": args.experiment_name or args.experiment_key,
                "cohort": args.experiment_cohort,
                "hypothesis": args.experiment_hypothesis,
                "suite_id": args.suite_id or derive_suite_id(case_ids),
                "project_id": args.project_id,
                "min_runs_per_cohort": args.min_runs_per_cohort,
            }
        payload = build_persistence_payload(
            run,
            agent_slug=args.agent_slug,
            suite_id=args.suite_id or derive_suite_id(case_ids),
            run_kind="completion_review_benchmark",
            use_memory=args.use_memory,
            seed=args.seed,
            config_snapshot=config_snapshot,
            metadata={
                "reviewer_role": True,
                "reviewer_agent_slug": "supervisor",
                "reviewer_models": list(run.models),
            },
            experiment=experiment_payload,
        )
        persisted_run_id = await persist_benchmark_payload(payload)
        if args.experiment_key:
            async with async_session() as db:
                experiment_summary = await get_benchmark_experiment_summary_by_key(
                    db, args.experiment_key
                )

    output = {
        **run.to_dict(),
        "persisted_run_id": persisted_run_id,
        "suite_id": args.suite_id or derive_suite_id(case_ids),
        "experiment_summary": experiment_summary,
    }
    rendered = json.dumps(output, indent=2)
    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(rendered)
    print(rendered)


if __name__ == "__main__":
    asyncio.run(main())
