"""Decision logic for the persona honing experiment: supervisor review and final decision."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_hub import AsyncAgentHubClient
from sqlalchemy import select

from app.db import async_session
from app.services.persona_prompt_service import render_persona_improvement_decision_review_prompt
from scripts.persona_honing._formatting import (
    _format_experiment_summary_block,
    _format_improvement_summary_block,
)
from scripts.persona_honing._models import PersonaHoningIteration, _IterationConfig
from scripts.persona_honing._response import parse_decision_review_content


def _needs_supervisor_review(
    *,
    raw_decision: str,
    raw_reason: str,
    review_summary: dict[str, Any] | None,
    field_snapshot: dict[str, Any] | None,
) -> bool:
    if raw_decision == "hold":
        return True
    if raw_reason == "candidate_matches_quality_with_fewer_tool_calls":
        return True
    if review_summary is not None and str(review_summary.get("decision")) == "hold":
        return True
    return bool(dict((field_snapshot or {}).get("review_gate") or {}).get("needs_review"))


async def _persist_final_experiment_decision(
    *,
    experiment_key: str,
    decision: str,
    reason: str,
    source: str,
    field_snapshot: dict[str, Any] | None,
    decision_review: dict[str, Any] | None,
) -> None:
    from app.models import AgentBenchmarkExperiment

    async with async_session() as db:
        experiment = await db.scalar(
            select(AgentBenchmarkExperiment).where(
                AgentBenchmarkExperiment.experiment_key == experiment_key
            )
        )
        if experiment is None:
            return
        evidence = dict(experiment.evidence or {})
        evidence["final_decision_source"] = source
        if field_snapshot:
            evidence["field_gate"] = dict(field_snapshot.get("review_gate") or {})
            evidence["field_overview"] = dict(field_snapshot.get("overview") or {})
        if decision_review:
            evidence["supervisor_review"] = decision_review
        experiment.decision = decision
        experiment.decision_reason = reason
        experiment.status = "closed" if decision in {"promote", "rollback"} else "open"
        experiment.evidence = evidence
        await db.commit()


async def _run_decision_review(
    *,
    client: AsyncAgentHubClient,
    iteration: int,
    experiment_key: str,
    project_id: str,
    timeout_seconds: float | None,
    working_root: Path,
    proposed_decision: str,
    proposed_reason: str,
    experiment_summary: dict[str, Any],
    review_summary: dict[str, Any] | None,
    field_snapshot: dict[str, Any] | None,
    record: PersonaHoningIteration,
) -> dict[str, Any]:
    from app.services.persona_improvement import build_persona_heartbeat_field_digest

    prompt = await render_persona_improvement_decision_review_prompt(
        proposed_decision=proposed_decision,
        proposed_reason=proposed_reason,
        experiment_summary_block=_format_experiment_summary_block(experiment_summary),
        completion_review_block=_format_experiment_summary_block(review_summary),
        field_signals_block=await build_persona_heartbeat_field_digest(),
        improvement_summary_block=_format_improvement_summary_block(record),
    )
    try:
        response = await client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug="supervisor",
            external_id=f"persona-honing-review:{experiment_key}:iteration-{iteration}",
            enable_caching=False, skip_cache=True, use_memory=False, max_turns=1,
            working_dir=str(working_root), execute_tools=False, timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        return {
            "used": False, "session_id": None, "decision": None,
            "reason": f"review_unavailable:{type(exc).__name__}",
        }
    parsed = parse_decision_review_content(response.content)
    if parsed is None:
        return {
            "used": False, "session_id": response.session_id, "decision": None,
            "reason": "review_unparseable", "raw_content": response.content,
        }
    return {
        "used": True, "session_id": response.session_id,
        "decision": parsed["decision"], "reason": parsed["reason"],
        "raw_content": response.content,
        "field_gate": dict((field_snapshot or {}).get("review_gate") or {}),
    }


async def _determine_final_experiment_decision(
    *,
    client: AsyncAgentHubClient,
    iteration: int,
    record: PersonaHoningIteration,
    experiment_key: str,
    experiment_summary: dict[str, Any],
    review_summary: dict[str, Any] | None,
    field_snapshot: dict[str, Any] | None,
    cfg: _IterationConfig,
) -> tuple[str, str, str, dict[str, Any] | None]:
    raw_decision = str(experiment_summary.get("decision") or "hold")
    raw_reason = str(experiment_summary.get("decision_reason") or "no_clear_winner")
    review_decision = str(review_summary.get("decision")) if review_summary is not None else None
    if review_decision == "rollback":
        review_reason = str(review_summary.get("decision_reason") or "completion_review_regression")
        return "rollback", review_reason, "completion_review", None
    if not _needs_supervisor_review(
        raw_decision=raw_decision, raw_reason=raw_reason,
        review_summary=review_summary, field_snapshot=field_snapshot,
    ):
        return raw_decision, raw_reason, "benchmark", None
    decision_review = await _run_decision_review(
        client=client, iteration=iteration, experiment_key=experiment_key,
        project_id=cfg["project_id"], timeout_seconds=cfg["timeout_seconds"],
        working_root=cfg["working_root"], proposed_decision=raw_decision,
        proposed_reason=raw_reason, experiment_summary=experiment_summary,
        review_summary=review_summary, field_snapshot=field_snapshot, record=record,
    )
    if decision_review.get("used"):
        return (
            str(decision_review["decision"]), str(decision_review["reason"]),
            "supervisor_review", decision_review,
        )
    return raw_decision, raw_reason, "benchmark", decision_review
