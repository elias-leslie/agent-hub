"""Execution helpers for the agent output contract benchmark."""

from __future__ import annotations

import itertools
import time

from agent_hub import AsyncAgentHubClient

from scripts.agent_output_benchmark_cases import get_case_by_id
from scripts.agent_output_benchmark_eval import (
    AgentOutputBenchmarkAttempt,
    score_output_contract_attempt,
)
from scripts.persona_benchmark_runner import _fetch_used_tool_names

TASK_TYPE = "task"
CLIENT_NAME = "agent-output-benchmark"
REQUEST_SOURCE = "backend/scripts/run_agent_output_benchmark.py"
CLI_COMMAND = "run_agent_output_benchmark"
BENCHMARK_ID_MEMORY_PREFIX = "agent-output-benchmark"


def _build_attempt_message(case_prompt: str, requested_model: str, explicit_model_override: bool) -> str:
    if explicit_model_override:
        return f"@{requested_model}\n{case_prompt}"
    return case_prompt


def _score_failed_attempt(*, case, requested_model: str, run_number: int, latency_ms: int, exc: Exception) -> AgentOutputBenchmarkAttempt:
    return score_output_contract_attempt(
        case=case,
        model_id=requested_model,
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


async def _score_successful_attempt(*, case, requested_model: str, run_number: int, latency_ms: int, response) -> AgentOutputBenchmarkAttempt:
    used_tool_names = await _fetch_used_tool_names(response.session_id)
    return score_output_contract_attempt(
        case=case,
        model_id=requested_model,
        run_number=run_number,
        latency_ms=latency_ms,
        content=response.content,
        session_id=response.session_id,
        provider=response.provider,
        effective_model=response.model,
        fallback_used=response.model != requested_model,
        turns=response.turns,
        tool_calls_count=response.tool_calls_count,
        used_tool_names=used_tool_names,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        total_tokens=response.usage.total_tokens,
    )


async def run_one_attempt(
    *,
    client: AsyncAgentHubClient,
    benchmark_id: str,
    project_id: str,
    agent_slug: str,
    requested_model: str,
    explicit_model_override: bool,
    case_id: str,
    run_number: int,
    timeout_seconds: float | None,
    use_memory: bool,
    memory_group_id: str,
    build_external_id,
) -> AgentOutputBenchmarkAttempt:
    case = get_case_by_id(agent_slug, case_id)
    message_content = _build_attempt_message(case.prompt, requested_model, explicit_model_override)
    started = time.perf_counter()
    try:
        response = await client.complete(
            messages=[{"role": "user", "content": message_content}],
            project_id=project_id,
            agent_slug=agent_slug,
            task_type=TASK_TYPE,
            external_id=build_external_id(agent_slug, case.case_id, run_number),
            enable_caching=False,
            skip_cache=True,
            use_memory=use_memory,
            memory_group_id=memory_group_id,
            max_turns=case.max_turns,
            execute_tools=case.execute_tools,
            timeout_seconds=timeout_seconds,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return await _score_successful_attempt(
            case=case, requested_model=requested_model, run_number=run_number,
            latency_ms=latency_ms, response=response,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _score_failed_attempt(
            case=case, requested_model=requested_model, run_number=run_number,
            latency_ms=latency_ms, exc=exc,
        )


async def collect_all_attempts(
    *,
    client: AsyncAgentHubClient,
    benchmark_id: str,
    project_id: str,
    agent_slug: str,
    requested_models: list[str],
    explicit_model_override: bool,
    case_ids: list[str],
    runs_per_case: int,
    timeout_seconds: float | None,
    use_memory: bool,
    seed: int,
    memory_group_id: str | None,
    build_external_id,
) -> list[AgentOutputBenchmarkAttempt]:
    attempts: list[AgentOutputBenchmarkAttempt] = []
    combos = itertools.product(range(1, runs_per_case + 1), requested_models, case_ids)
    for run_number, requested_model, case_id in combos:
        resolved_memory_group = memory_group_id or f"{BENCHMARK_ID_MEMORY_PREFIX}:{agent_slug}:{seed}:{run_number}"
        attempt = await run_one_attempt(
            client=client, benchmark_id=benchmark_id, project_id=project_id,
            agent_slug=agent_slug, requested_model=requested_model,
            explicit_model_override=explicit_model_override, case_id=case_id,
            run_number=run_number, timeout_seconds=timeout_seconds,
            use_memory=use_memory, memory_group_id=resolved_memory_group,
            build_external_id=build_external_id,
        )
        attempts.append(attempt)
    return attempts
