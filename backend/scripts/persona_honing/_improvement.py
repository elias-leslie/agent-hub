"""Improvement prompt building and improvement pass execution."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_hub import AsyncAgentHubClient

from app.services.persona_prompt_service import render_persona_improvement_prompt
from scripts.completion_review_benchmark_eval import CompletionReviewBenchmarkRun
from scripts.persona_benchmark_eval import PersonaBenchmarkRun
from scripts.persona_benchmark_runner import _fetch_used_tool_names
from scripts.persona_honing._clusters import (
    _diff_failure_clusters,
    _group_failures,
    _render_cluster_block,
)
from scripts.persona_honing._response import _HONING_RESPONSE_SCHEMA, parse_improvement_content
from scripts.persona_honing._signals import _load_recent_improvement_signals

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


def _build_review_prompt_blocks(
    review_run: CompletionReviewBenchmarkRun | None,
    previous_review_clusters: list[dict[str, Any]] | None,
    max_failures: int,
) -> tuple[str, str, str]:
    """Return (review_ranking_block, review_failure_block, review_persistent_block)."""
    if review_run is None:
        return (
            "- not run",
            "Completion-review failure clusters:\n- not run",
            "Persistent completion-review clusters from the previous iteration:\n- not run",
        )
    review_ranking_lines = [
        f"- rank={i} model={s.model_id} avg_score={s.avg_composite_score:.1f} "
        f"pass_rate={s.pass_rate:.1f} avg_turns={s.avg_turns:.2f}"
        for i, s in enumerate(review_run.summaries[:3], start=1)
    ]
    review_clusters = _group_failures(review_run.attempts)
    review_persistent_clusters, _, _ = _diff_failure_clusters(previous_review_clusters, review_clusters)
    return (
        "\n".join(review_ranking_lines) if review_ranking_lines else "- none",
        _render_cluster_block(review_clusters[:max_failures], "Completion-review failure clusters"),
        _render_cluster_block(
            review_persistent_clusters[:max_failures],
            "Persistent completion-review clusters from the previous iteration",
        ),
    )


async def _build_improvement_prompt(
    *,
    run: PersonaBenchmarkRun,
    iteration: int,
    previous_clusters: list[dict[str, Any]] | None,
    review_run: CompletionReviewBenchmarkRun | None,
    previous_review_clusters: list[dict[str, Any]] | None,
    improvement_signals: str | None,
    field_signals: str | None,
    max_failures: int = 6,
) -> str:
    current_clusters = _group_failures(run.attempts)
    persistent_clusters, new_clusters, resolved_clusters = _diff_failure_clusters(
        previous_clusters, current_clusters,
    )
    ranking_block = "\n".join(
        f"- rank={i} model={s.model_id} avg_score={s.avg_composite_score:.1f} "
        f"pass_rate={s.pass_rate:.3f} avg_tools={s.avg_tool_calls:.1f}"
        for i, s in enumerate(run.summaries[:3], start=1)
    ) or "- none"
    review_ranking_block, review_failure_block, review_persistent_block = (
        _build_review_prompt_blocks(review_run, previous_review_clusters, max_failures)
    )
    return await render_persona_improvement_prompt(
        iteration=iteration,
        ranking_block=ranking_block,
        failure_block=_render_cluster_block(current_clusters[:max_failures], "Top failure clusters"),
        persistent_block=_render_cluster_block(
            persistent_clusters[:max_failures],
            "Persistent unresolved clusters from the previous iteration",
        ),
        new_block=_render_cluster_block(new_clusters[:max_failures], "New clusters this iteration"),
        resolved_block=_render_cluster_block(
            resolved_clusters[:max_failures], "Resolved clusters since the previous iteration",
        ),
        review_ranking_block=review_ranking_block,
        review_failure_block=review_failure_block,
        review_persistent_block=review_persistent_block,
        improvement_signals_block=improvement_signals or "- none",
        field_signals_block=field_signals or "- none",
        reference_block="\n".join(f"- {note}" for note in _REFERENCE_NOTES),
    )


async def _run_improvement_pass(
    *,
    client: AsyncAgentHubClient,
    project_id: str,
    iteration: int,
    run: PersonaBenchmarkRun,
    previous_clusters: list[dict[str, Any]] | None,
    review_run: CompletionReviewBenchmarkRun | None,
    previous_review_clusters: list[dict[str, Any]] | None,
    timeout_seconds: float | None,
    working_root: Path,
) -> tuple[str | None, str, list[str], dict[str, Any] | None]:
    """Prompt the persona to improve itself based on benchmark failures."""
    from app.services.persona_improvement import build_persona_heartbeat_field_digest

    improvement_signals = await _load_recent_improvement_signals(project_id)
    field_signals = await build_persona_heartbeat_field_digest()
    prompt = await _build_improvement_prompt(
        run=run, iteration=iteration, previous_clusters=previous_clusters,
        review_run=review_run, previous_review_clusters=previous_review_clusters,
        improvement_signals=improvement_signals, field_signals=field_signals,
    )
    response = await client.complete(
        messages=[{"role": "user", "content": prompt}],
        project_id=project_id, agent_slug="persona",
        external_id=f"persona-honing:{run.benchmark_id}:iteration-{iteration}",
        enable_caching=False, skip_cache=True, use_memory=False, max_turns=12,
        working_dir=str(working_root), execute_tools=True, timeout_seconds=timeout_seconds,
        response_format={"type": "json_object", "schema": _HONING_RESPONSE_SCHEMA},
    )
    used_tools = await _fetch_used_tool_names(response.session_id)
    return response.session_id, response.content, used_tools, parse_improvement_content(response.content)
