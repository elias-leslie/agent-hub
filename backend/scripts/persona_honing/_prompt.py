"""Persona honing prompt construction."""
from __future__ import annotations

import json
from typing import Any

from scripts.completion_review_benchmark_eval import CompletionReviewBenchmarkRun
from scripts.persona_benchmark_eval import (
    PersonaBenchmarkRun,
    _load_first_json_object,
    _strip_leading_narration_tags,
    strip_markdown_fences,
)
from scripts.persona_honing._clusters import (
    _diff_failure_clusters,
    _group_failures,
    _render_cluster_block,
)

_HONING_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "changes_applied": {"type": "array", "items": {"type": "string"}},
        "next_focus": {"type": "array", "items": {"type": "string"}},
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


def build_honing_prompt(
    run: PersonaBenchmarkRun,
    iteration: int,
    previous_clusters: list[dict[str, Any]] | None = None,
    review_run: CompletionReviewBenchmarkRun | None = None,
    previous_review_clusters: list[dict[str, Any]] | None = None,
    improvement_signals: str | None = None,
    max_failures: int = 6,
) -> str:
    """Build the persona self-improvement prompt for one benchmark run."""
    current_clusters = _group_failures(run.attempts)
    persistent_clusters, new_clusters, resolved_clusters = _diff_failure_clusters(
        previous_clusters, current_clusters,
    )
    ranking_lines = [
        f"- rank={i} model={s.model_id} avg_score={s.avg_composite_score:.1f} "
        f"pass_rate={s.pass_rate:.3f} avg_tools={s.avg_tool_calls:.1f}"
        for i, s in enumerate(run.summaries[:3], start=1)
    ]
    ranking_block = "\n".join(ranking_lines) if ranking_lines else "- none"
    reference_block = "\n".join(f"- {note}" for note in _REFERENCE_NOTES)
    failure_block = _render_cluster_block(current_clusters[:max_failures], "Top failure clusters")
    persistent_block = _render_cluster_block(
        persistent_clusters[:max_failures], "Persistent unresolved clusters from the previous iteration",
    )
    new_block = _render_cluster_block(new_clusters[:max_failures], "New clusters this iteration")
    resolved_block = _render_cluster_block(
        resolved_clusters[:max_failures], "Resolved clusters since the previous iteration",
    )
    review_ranking_block = "- not run"
    review_failure_block = "Completion-review failure clusters:\n- not run"
    review_persistent_block = "Persistent completion-review clusters from the previous iteration:\n- not run"
    improvement_signals_block = improvement_signals.strip() if improvement_signals else "- none"
    if review_run is not None:
        review_ranking_lines = [
            f"- rank={i} model={s.model_id} avg_score={s.avg_composite_score:.1f} "
            f"pass_rate={s.pass_rate:.1f} avg_turns={s.avg_turns:.2f}"
            for i, s in enumerate(review_run.summaries[:3], start=1)
        ]
        review_ranking_block = "\n".join(review_ranking_lines) if review_ranking_lines else "- none"
        review_clusters = _group_failures(review_run.attempts)
        review_persistent_clusters, _, _ = _diff_failure_clusters(
            previous_review_clusters,
            review_clusters,
        )
        review_failure_block = _render_cluster_block(
            review_clusters[:max_failures],
            "Completion-review failure clusters",
        )
        review_persistent_block = _render_cluster_block(
            review_persistent_clusters[:max_failures],
            "Persistent completion-review clusters from the previous iteration",
        )

    return (
        f"You are the persona reviewing your own benchmark results for honing iteration {iteration}.\n\n"
        "Your job is to improve your own operating model only where the evidence justifies it.\n"
        "Stay inside persona-internal adaptation work: heartbeat instructions, model review, "
        "performance logging, and durable memory. Do not create or dispatch project tasks.\n\n"
        "Benchmark ranking:\n"
        f"{ranking_block}\n\n"
        f"{failure_block}\n\n"
        f"{persistent_block}\n\n"
        f"{new_block}\n\n"
        f"{resolved_block}\n\n"
        "Completion-review benchmark ranking:\n"
        f"{review_ranking_block}\n\n"
        f"{review_failure_block}\n\n"
        f"{review_persistent_block}\n\n"
        "Recent improvement signals:\n"
        f"{improvement_signals_block}\n\n"
        "Reference heuristics to borrow when relevant:\n"
        f"{reference_block}\n\n"
        "Required behavior:\n"
        "- Diagnose the canonical layer first: heartbeat instructions, memory retrieval, observability, or model config.\n"
        "- When reviewing your own performance history, use agent_slug=\"persona\" rather than a display name string.\n"
        "- Use repeated issue clusters, benchmark decisions, and low-yield reference evidence to choose the smallest effective fix.\n"
        "- If you change heartbeat instructions, read them first and make a small targeted edit.\n"
        "- If model assignment looks implicated, inspect model/performance tools before changing config.\n"
        "- If memory routing looks implicated, inspect current agent memory config first and use manage_memory_tags for reference-tier retagging before editing heartbeat instructions.\n"
        "- If a specialist keeps missing universal workflow rules like rebuild.sh or dt, inspect mandate/guardrail exposure before retagging references.\n"
        "- Treat audience tags and reference inclusion as the memory-routing levers; do not paper over routing misses by inventing new mandates or guardrails.\n"
        "- Treat completion-review regressions as first-class evidence; inspect completion-review-prompt, completion-review-rules, or supervisor model config when reviewer cases fail.\n"
        "- Keep reviewer edits small and targeted; do not rewrite working reviewer behavior because of one ambiguous case.\n"
        "- If improvement signals show a recurring self-correction failure that this battery does not directly cover, call that out in next_focus as a benchmark coverage gap rather than overfitting the current prompt to an untested pattern.\n"
        "- Log a performance observation if the benchmark exposed a real recurring issue or confirmed an improvement.\n"
        "- Save durable memory only for reusable cross-session lessons.\n"
        "- Do not add speculative retry/safety mechanisms without demonstrated need.\n\n"
        "Return JSON only with fields summary, changes_applied, next_focus, durable_learning_saved."
    )


def _parse_improvement_content(content: str) -> dict[str, Any] | None:
    cleaned = strip_markdown_fences(_strip_leading_narration_tags(content))
    try:
        parsed = _load_first_json_object(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
