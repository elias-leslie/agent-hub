#!/usr/bin/env python3
"""Run live Jenny benchmark cases across multiple candidate models."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import shutil
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = ROOT / "backend" / ".venv" / "bin" / "python"

if (
    VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
    and os.environ.get("JENNY_BENCHMARK_NO_REEXEC") != "1"
):
    os.environ["JENNY_BENCHMARK_NO_REEXEC"] = "1"
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "packages" / "agent-hub-client"))

from agent_hub import AsyncAgentHubClient
from sqlalchemy import select, text

from app.db import async_session
from app.models.session import SessionEvent
from app.services.agent_benchmark_service import (
    capture_benchmark_config_snapshot,
    persist_benchmark_payload,
)
from scripts.jenny_benchmark_cases import (
    DEFAULT_JENNY_BENCHMARK_MODELS,
    get_case_by_id,
    get_jenny_benchmark_cases,
    prepare_case_workspace,
)
from scripts.jenny_benchmark_eval import (
    JennyBenchmarkAttempt,
    JennyBenchmarkRun,
    score_attempt,
    summarize_attempts,
)
from scripts.jenny_benchmark_report import generate_markdown_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


_BENCHMARK_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "case_id": {"type": "string"},
        "primary_action": {"enum": ["dispatch", "monitor", "block", "wait", "reconcile"]},
        "should_dispatch": {"type": "boolean"},
        "should_close": {"type": "boolean"},
        "confidence": {"enum": ["low", "medium", "high"]},
        "summary": {"type": "string"},
    },
    "required": [
        "case_id",
        "primary_action",
        "should_dispatch",
        "should_close",
        "confidence",
        "summary",
    ],
}


def _parse_csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def derive_suite_id(case_ids: list[str]) -> str:
    """Build a stable suite identifier for a benchmark battery."""
    normalized = sorted(set(case_ids))
    if len(normalized) == 1:
        return normalized[0]
    digest = hashlib.sha256(",".join(normalized).encode("utf-8")).hexdigest()[:8]
    return f"benchmark-suite-{digest}"


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


def build_persistence_payload(
    run: JennyBenchmarkRun,
    *,
    agent_slug: str,
    suite_id: str,
    run_kind: str,
    use_memory: bool,
    seed: int | None,
    config_snapshot: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Normalize a benchmark run into the persisted DB payload shape."""
    attempts = [attempt.to_dict() for attempt in run.attempts]
    attempt_count = len(attempts)
    passed_attempt_count = sum(1 for attempt in run.attempts if attempt.passed)
    infra_failure_count = sum(1 for attempt in run.attempts if attempt.infra_failure)
    avg_score = round(
        sum(float(attempt.composite_score) for attempt in run.attempts) / attempt_count,
        1,
    ) if attempt_count else 0.0
    pass_rate = round((passed_attempt_count / attempt_count) * 100, 1) if attempt_count else 0.0

    normalized_attempts: list[dict[str, object]] = []
    for attempt in attempts:
        parsed = attempt.get("parsed") if isinstance(attempt.get("parsed"), dict) else {}
        normalized_attempts.append(
            {
                **attempt,
                "primary_action": parsed.get("primary_action"),
                "should_dispatch": parsed.get("should_dispatch"),
                "should_close": parsed.get("should_close"),
                "confidence": parsed.get("confidence"),
                "summary": parsed.get("summary"),
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
        "avg_score": avg_score,
        "pass_rate": pass_rate,
        "attempt_count": attempt_count,
        "passed_attempt_count": passed_attempt_count,
        "infra_failure_count": infra_failure_count,
        "config_snapshot": dict(config_snapshot or {}),
        "metadata": dict(metadata or {}),
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "attempts": normalized_attempts,
    }


async def _fetch_used_tool_names(session_id: str | None) -> list[str]:
    """Return ordered unique tool names used in a benchmark session."""
    if not session_id:
        return []

    query = (
        select(SessionEvent.tool_name)
        .where(
            SessionEvent.session_id == session_id,
            SessionEvent.event_type == "tool_use",
            SessionEvent.tool_name.is_not(None),
        )
        .order_by(SessionEvent.turn, SessionEvent.sequence)
    )
    async with async_session() as db:
        rows = (await db.execute(query)).scalars().all()

    seen: set[str] = set()
    tool_names: list[str] = []
    for tool_name in rows:
        if not tool_name or tool_name in seen:
            continue
        seen.add(tool_name)
        tool_names.append(tool_name)
    return tool_names


async def _resolve_client_id(explicit_client_id: str | None, project_id: str) -> str:
    """Resolve an active client id for local benchmark API calls."""
    if explicit_client_id:
        return explicit_client_id

    env_client_id = os.environ.get("AGENT_HUB_CLIENT_ID")
    if env_client_id:
        return env_client_id

    from app.db import async_session
    query = text(
        """
        SELECT id, display_name, client_type, allowed_projects
        FROM clients
        WHERE status = 'active'
        ORDER BY
            CASE WHEN allowed_projects IS NULL THEN 0 ELSE 1 END,
            CASE WHEN client_type = 'internal' THEN 0 ELSE 1 END,
            display_name ASC
        """
    )

    async with async_session() as db:
        rows = (await db.execute(query)).mappings().all()

    for row in rows:
        allowed_projects = row["allowed_projects"]
        if allowed_projects is None:
            return str(row["id"])
        try:
            projects = json.loads(allowed_projects)
        except json.JSONDecodeError:
            continue
        if isinstance(projects, list) and project_id in projects:
            return str(row["id"])

    raise RuntimeError(
        f"No active client found with access to project '{project_id}'. "
        "Pass --client-id or set AGENT_HUB_CLIENT_ID."
    )


async def _run_one_attempt(
    *,
    client: AsyncAgentHubClient,
    benchmark_id: str,
    project_id: str,
    model_id: str,
    case_id: str,
    run_number: int,
    working_root: Path,
    timeout_seconds: float,
    keep_workdirs: bool,
    use_memory: bool,
    memory_group_id: str,
) -> JennyBenchmarkAttempt:
    case = get_case_by_id(case_id)
    workdir = working_root / benchmark_id / model_id.replace("/", "__") / case.case_id / f"run-{run_number}"
    if case.fixture_files:
        prepare_case_workspace(case, workdir)

    message_content = f"@{model_id}\n{case.build_prompt()}"
    started = time.perf_counter()
    try:
        response = await client.complete(
            messages=[{"role": "user", "content": message_content}],
            project_id=project_id,
            agent_slug="persona",
            task_type="wake",
            external_id=f"jenny-benchmark:{benchmark_id}:{case.case_id}:run-{run_number}",
            enable_caching=False,
            skip_cache=True,
            use_memory=use_memory,
            memory_group_id=memory_group_id,
            max_turns=case.max_turns,
            working_dir=str(workdir) if case.fixture_files else None,
            execute_tools=case.execute_tools,
            timeout_seconds=timeout_seconds,
            disable_agent_fallbacks=True,
            response_format={
                "type": "json_object",
                "schema": _BENCHMARK_RESPONSE_SCHEMA,
            },
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        used_tool_names = await _fetch_used_tool_names(response.session_id)
        attempt = score_attempt(
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
        attempt = score_attempt(
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

    if case.fixture_files and not keep_workdirs:
        shutil.rmtree(workdir, ignore_errors=True)
    return attempt


async def run_benchmark(
    *,
    models: list[str],
    case_ids: list[str],
    runs_per_case: int,
    project_id: str,
    working_root: Path,
    seed: int,
    timeout_seconds: float,
    keep_workdirs: bool,
    base_url: str,
    client_id: str | None,
    use_memory: bool,
    memory_group_id: str | None,
) -> JennyBenchmarkRun:
    benchmark_id = f"jenny-benchmark-{uuid.uuid4().hex[:8]}"
    started_at = datetime.now(UTC).isoformat()
    attempts: list[JennyBenchmarkAttempt] = []
    _validate_case_project_requirements(case_ids, project_id)
    order = _build_attempt_order(models, case_ids, runs_per_case, seed)
    resolved_client_id = await _resolve_client_id(client_id, project_id)
    resolved_memory_group_id = memory_group_id or f"benchmark:{benchmark_id}"

    async with AsyncAgentHubClient(
        base_url=base_url,
        client_name="jenny-model-benchmark",
        client_id=resolved_client_id,
        request_source="backend/scripts/run_jenny_model_benchmark.py",
        cli_command="run_jenny_model_benchmark",
    ) as client:
        for index, (model_id, case_id, run_number) in enumerate(order, start=1):
            logger.info(
                "[%d/%d] model=%s case=%s run=%d",
                index,
                len(order),
                model_id,
                case_id,
                run_number,
            )
            attempt = await _run_one_attempt(
                client=client,
                benchmark_id=benchmark_id,
                project_id=project_id,
                model_id=model_id,
                case_id=case_id,
                run_number=run_number,
                working_root=working_root,
                timeout_seconds=timeout_seconds,
                keep_workdirs=keep_workdirs,
                use_memory=use_memory,
                memory_group_id=resolved_memory_group_id,
            )
            attempts.append(attempt)
            logger.info(
                "  score=%.1f passed=%s failure=%s latency=%dms tokens=%d",
                attempt.composite_score,
                attempt.passed,
                attempt.failure_detail or "-",
                attempt.latency_ms,
                attempt.total_tokens,
            )

    completed_at = datetime.now(UTC).isoformat()
    summaries = summarize_attempts(attempts)
    return JennyBenchmarkRun(
        benchmark_id=benchmark_id,
        project_id=project_id,
        models=models,
        case_ids=case_ids,
        runs_per_case=runs_per_case,
        started_at=started_at,
        completed_at=completed_at,
        attempts=attempts,
        summaries=summaries,
    )


def _print_dry_run(models: list[str], case_ids: list[str], runs_per_case: int, seed: int) -> None:
    print("Jenny model benchmark dry run")
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


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run Jenny benchmark cases across model candidates")
    parser.add_argument("--agent-slug", default="persona", help="Agent slug to attribute benchmark history to")
    parser.add_argument("--models", help="Comma-separated model ids to test")
    parser.add_argument("--cases", help="Comma-separated benchmark case ids to run")
    parser.add_argument("--suite-id", help="Stable suite identifier for trend/history grouping")
    parser.add_argument("--runs-per-case", type=int, default=3, help="Runs per model per case")
    parser.add_argument("--project-id", default="agent-hub", help="Project id for benchmark sessions")
    parser.add_argument(
        "--working-root",
        default=str(ROOT / "backend" / ".tmp" / "jenny-model-benchmark"),
        help="Root directory for temporary benchmark workspaces",
    )
    parser.add_argument("--seed", type=int, default=42, help="Shuffle seed for attempt order")
    parser.add_argument("--timeout-seconds", type=float, default=180.0, help="Per-turn timeout")
    parser.add_argument("--base-url", default="http://localhost:8003", help="Agent Hub base URL")
    parser.add_argument("--client-id", help="Registered Agent Hub client id for access control")
    parser.add_argument("--output-json", help="Write full JSON result to this path")
    parser.add_argument("--output-md", help="Write markdown report to this path")
    parser.add_argument("--keep-workdirs", action="store_true", help="Keep temporary workspaces")
    parser.add_argument("--use-memory", action="store_true", help="Enable Jenny memory injection for full-context benchmark runs")
    parser.add_argument("--memory-group-id", help="Explicit memory group id to use when memory injection is enabled")
    parser.add_argument("--no-persist", action="store_true", help="Skip saving results to the benchmark history tables")
    parser.add_argument("--dry-run", action="store_true", help="Print roster and exit")
    args = parser.parse_args()

    models = _parse_csv(args.models, DEFAULT_JENNY_BENCHMARK_MODELS)
    all_case_ids = [case.case_id for case in get_jenny_benchmark_cases()]
    case_ids = _parse_csv(args.cases, all_case_ids)

    if args.dry_run:
        _print_dry_run(models, case_ids, args.runs_per_case, args.seed)
        return

    run = await run_benchmark(
        models=models,
        case_ids=case_ids,
        runs_per_case=args.runs_per_case,
        project_id=args.project_id,
        working_root=Path(args.working_root),
        seed=args.seed,
        timeout_seconds=args.timeout_seconds,
        keep_workdirs=args.keep_workdirs,
        base_url=args.base_url,
        client_id=args.client_id,
        use_memory=args.use_memory,
        memory_group_id=args.memory_group_id,
    )

    report = generate_markdown_report(run)
    persisted_run_id: str | None = None
    if not args.no_persist:
        config_snapshot = await capture_benchmark_config_snapshot(args.agent_slug)
        payload = build_persistence_payload(
            run,
            agent_slug=args.agent_slug,
            suite_id=args.suite_id or derive_suite_id(case_ids),
            run_kind="benchmark",
            use_memory=args.use_memory,
            seed=args.seed,
            config_snapshot=config_snapshot,
            metadata={"report_generated": True},
        )
        persisted_run_id = await persist_benchmark_payload(payload)
        logger.info("Persisted benchmark run as %s", persisted_run_id)
    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(
                {
                    **run.to_dict(),
                    "persisted_run_id": persisted_run_id,
                    "suite_id": args.suite_id or derive_suite_id(case_ids),
                },
                indent=2,
            )
        )
        logger.info("JSON results written to %s", args.output_json)
    if args.output_md:
        output_md = Path(args.output_md)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(report)
        logger.info("Markdown report written to %s", args.output_md)
    if not args.output_md:
        print(report)


if __name__ == "__main__":
    asyncio.run(main())
