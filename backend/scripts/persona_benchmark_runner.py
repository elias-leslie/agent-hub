"""Attempt execution helpers for the persona model benchmark."""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select, text

if TYPE_CHECKING:
    from agent_hub import AsyncAgentHubClient

from app.db import async_session
from app.models.session import SessionEvent
from scripts.persona_benchmark_cases import get_case_by_id, prepare_case_workspace
from scripts.persona_benchmark_eval import PersonaBenchmarkAttempt, score_attempt

logger = logging.getLogger(__name__)

_AGENT_SLUG = "persona"
_BENCHMARK_ID_PREFIX = "persona-benchmark"
_EVENT_TYPE_TOOL_USE = "tool_use"
_ENV_CLIENT_ID = "AGENT_HUB_CLIENT_ID"
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
        "case_id", "primary_action", "should_dispatch",
        "should_close", "confidence", "summary",
    ],
}


async def _fetch_used_tool_names(session_id: str | None) -> list[str]:
    """Return ordered unique tool names used in a benchmark session."""
    if not session_id:
        return []
    query = (
        select(SessionEvent.tool_name)
        .where(
            SessionEvent.session_id == session_id,
            SessionEvent.event_type == _EVENT_TYPE_TOOL_USE,
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
    if env_id := os.environ.get(_ENV_CLIENT_ID):
        return env_id
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


def _score_kwargs_success(case, model_id, run_number, latency_ms, response, used_tool_names):
    return dict(
        case=case, model_id=model_id, run_number=run_number, latency_ms=latency_ms,
        content=response.content, session_id=response.session_id,
        provider=response.provider, effective_model=response.model,
        fallback_used=response.model != model_id, turns=response.turns,
        tool_calls_count=response.tool_calls_count, used_tool_names=used_tool_names,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        total_tokens=response.usage.total_tokens,
    )


def _score_kwargs_failure(case, model_id, run_number, latency_ms, failure_detail):
    return dict(
        case=case, model_id=model_id, run_number=run_number, latency_ms=latency_ms,
        content="", session_id=None, provider=None, effective_model=None,
        fallback_used=False, turns=0, tool_calls_count=0, used_tool_names=[],
        input_tokens=0, output_tokens=0, total_tokens=0,
        failure_detail=failure_detail,
    )


def _build_complete_kwargs(
    case,
    *,
    benchmark_id: str,
    project_id: str,
    model_id: str,
    run_number: int,
    workdir: Path,
    use_memory: bool,
    memory_group_id: str,
    memory_variant_override: str | None,
    timeout_seconds: float | None,
    task_type: str,
    persona_name: str,
) -> dict:
    return dict(
        messages=[{"role": "user", "content": f"@{model_id}\n{case.build_prompt(persona_name)}"}],
        project_id=project_id,
        agent_slug=_AGENT_SLUG,
        external_id=f"{_BENCHMARK_ID_PREFIX}:{benchmark_id}:{case.case_id}:run-{run_number}",
        enable_caching=False,
        skip_cache=True,
        use_memory=use_memory,
        memory_group_id=memory_group_id,
        memory_variant_override=memory_variant_override,
        max_turns=case.max_turns,
        working_dir=str(workdir) if case.fixture_files else None,
        execute_tools=case.execute_tools,
        timeout_seconds=timeout_seconds,
        task_type=task_type,
        disable_agent_fallbacks=True,
        response_format={"type": "json_object", "schema": _BENCHMARK_RESPONSE_SCHEMA},
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
    timeout_seconds: float | None,
    keep_workdirs: bool,
    use_memory: bool,
    memory_group_id: str,
    memory_variant_override: str | None,
    task_type: str,
    persona_name: str = "Persona",
) -> PersonaBenchmarkAttempt:
    case = get_case_by_id(case_id)
    workdir = working_root / benchmark_id / model_id.replace("/", "__") / case.case_id / f"run-{run_number}"
    if case.fixture_files:
        prepare_case_workspace(case, workdir)
    complete_kwargs = _build_complete_kwargs(
        case, benchmark_id=benchmark_id, project_id=project_id, model_id=model_id,
        run_number=run_number, workdir=workdir, use_memory=use_memory,
        memory_group_id=memory_group_id, memory_variant_override=memory_variant_override,
        timeout_seconds=timeout_seconds, task_type=task_type, persona_name=persona_name,
    )
    started = time.perf_counter()
    try:
        response = await client.complete(**complete_kwargs)
        latency_ms = int((time.perf_counter() - started) * 1000)
        used_tool_names = await _fetch_used_tool_names(response.session_id)
        attempt = score_attempt(**_score_kwargs_success(case, model_id, run_number, latency_ms, response, used_tool_names))
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        attempt = score_attempt(**_score_kwargs_failure(case, model_id, run_number, latency_ms, str(exc)))
    if case.fixture_files and not keep_workdirs:
        shutil.rmtree(workdir, ignore_errors=True)
    return attempt


async def _execute_attempt_loop(
    client: AsyncAgentHubClient,
    order: list[tuple[str, str, int]],
    *,
    benchmark_id: str,
    project_id: str,
    working_root: Path,
    timeout_seconds: float | None,
    keep_workdirs: bool,
    use_memory: bool,
    memory_group_id: str,
    memory_variant_override: str | None,
    task_type: str,
    persona_name: str,
) -> list[PersonaBenchmarkAttempt]:
    attempts: list[PersonaBenchmarkAttempt] = []
    for index, (model_id, case_id, run_number) in enumerate(order, start=1):
        logger.info("[%d/%d] model=%s case=%s run=%d", index, len(order), model_id, case_id, run_number)
        attempt = await _run_one_attempt(
            client=client, benchmark_id=benchmark_id, project_id=project_id,
            model_id=model_id, case_id=case_id, run_number=run_number,
            working_root=working_root, timeout_seconds=timeout_seconds,
            keep_workdirs=keep_workdirs, use_memory=use_memory,
            memory_group_id=memory_group_id, memory_variant_override=memory_variant_override,
            task_type=task_type,
            persona_name=persona_name,
        )
        attempts.append(attempt)
        logger.info(
            "  score=%.1f passed=%s failure=%s latency=%dms tokens=%d",
            attempt.composite_score, attempt.passed, attempt.failure_detail or "-",
            attempt.latency_ms, attempt.total_tokens,
        )
    return attempts
