"""Persistence for SummitFlow Work Chats verifier outcomes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentBenchmarkAttempt,
    AgentBenchmarkRun,
    AgentPerformanceLog,
    CostLog,
    Session,
)

SUITE_ID = "work-chats-verifier"
RUN_KIND = "verifier_outcome"
SCORE_BY_LABEL = {
    "PERFECT": 100,
    "VERIFIED": 90,
    "PARTIAL": 60,
    "FEEDBACK": 30,
    "FAILED": 0,
}


@dataclass(frozen=True)
class VerifierOutcomeResult:
    benchmark_id: str
    benchmark_run_id: str | None
    performance_log_id: int | None
    agent_slug: str
    model_id: str
    score: int
    outcome: str
    feedback_type: str
    created: bool


def _clean_text(value: object, *, limit: int | None = None) -> str:
    text = str(value or "").strip()
    if limit is not None:
        return text[:limit]
    return text


def _score_label(status: str | None, confidence: str | None) -> str:
    for value in (confidence, status):
        label = _clean_text(value).upper().replace(" ", "_").replace("-", "_")
        if label in SCORE_BY_LABEL:
            return label
    normalized_status = _clean_text(status).lower()
    if normalized_status in {"passed", "verified", "success", "succeeded"}:
        return "VERIFIED"
    if normalized_status in {"failed", "failure", "error"}:
        return "FAILED"
    return "PARTIAL"


def _claim_counts(payload: dict[str, Any]) -> tuple[int, int, int]:
    raw_claims = payload.get("atomic_claim_count")
    raw_passed = payload.get("atomic_pass_count")
    raw_failed = payload.get("atomic_fail_count")
    passed = max(0, int(raw_passed or 0))
    failed = max(0, int(raw_failed or 0))
    if raw_claims is None:
        claims = passed + failed
    else:
        claims = max(0, int(raw_claims or 0))
        if raw_failed is None:
            failed = max(0, claims - passed)
    passed = min(passed, claims) if claims else passed
    failed = min(failed, max(0, claims - passed)) if claims else failed
    return claims, passed, failed


def _score(payload: dict[str, Any]) -> tuple[str, int]:
    label = _score_label(payload.get("status"), payload.get("confidence"))
    base = SCORE_BY_LABEL[label]
    claims, passed, _failed = _claim_counts(payload)
    if claims > 0:
        atomic_score = round((passed / claims) * 100)
        base = round((base * 0.7) + (atomic_score * 0.3))
    return label, base


def _performance_outcome(label: str) -> tuple[str, str]:
    if label in {"PERFECT", "VERIFIED"}:
        return "success", "praise"
    if label == "FAILED":
        return "failure", "friction"
    return "partial", "friction"


def _benchmark_id(payload: dict[str, Any]) -> str:
    normalized = {
        "builder_session_id": payload.get("builder_session_id"),
        "verifier_session_id": payload.get("verifier_session_id"),
        "status": payload.get("status"),
        "confidence": payload.get("confidence"),
        "atomic_claim_count": payload.get("atomic_claim_count"),
        "atomic_pass_count": payload.get("atomic_pass_count"),
        "atomic_fail_count": payload.get("atomic_fail_count"),
        "feedback_loop_count": payload.get("feedback_loop_count"),
        "report_excerpt": payload.get("report_excerpt"),
    }
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    builder = _clean_text(payload.get("builder_session_id"))[:8] or "builder"
    verifier = _clean_text(payload.get("verifier_session_id"))[:8] or "verifier"
    return f"wcv-{builder}-{verifier}-{digest}"


def _session_model(session: Session) -> str:
    models_used = list(session.models_used or [])
    return _clean_text(models_used[-1] if models_used else session.model) or "unknown"


def _session_provider(session: Session) -> str | None:
    providers_used = list(session.providers_used or [])
    provider = providers_used[-1] if providers_used else session.provider
    return _clean_text(provider) or None


async def _cost_totals(db: AsyncSession, session_id: str) -> tuple[int, int]:
    result = await db.execute(
        select(
            func.coalesce(func.sum(CostLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(CostLog.output_tokens), 0).label("output_tokens"),
        ).where(CostLog.session_id == session_id)
    )
    row = result.one_or_none()
    if row is None:
        return 0, 0
    return int(row.input_tokens or 0), int(row.output_tokens or 0)


def _case_id(payload: dict[str, Any]) -> str:
    if task_id := _clean_text(payload.get("task_id")):
        return f"task:{task_id}"[:100]
    if project_id := _clean_text(payload.get("project_id")):
        return f"project:{project_id}"[:100]
    return "work-chat"


def _log_content(
    payload: dict[str, Any],
    *,
    label: str,
    score: int,
    agent_slug: str,
    model_id: str,
) -> str:
    claims, passed, failed = _claim_counts(payload)
    excerpt = _clean_text(payload.get("report_excerpt"), limit=1200)
    parts = [
        f"Work Chats verifier outcome for {agent_slug} ({model_id}): {label} score={score}.",
        f"builder_session={payload.get('builder_session_id')} verifier_session={payload.get('verifier_session_id')}.",
    ]
    if claims:
        parts.append(f"atomic_claims={claims} passed={passed} failed={failed}.")
    if payload.get("feedback_loop_count") is not None:
        parts.append(f"feedback_loops={int(payload.get('feedback_loop_count') or 0)}.")
    if excerpt:
        parts.append(f"Report excerpt: {excerpt}")
    return "\n".join(parts)


async def record_verifier_outcome(
    db: AsyncSession,
    payload: dict[str, Any],
) -> VerifierOutcomeResult:
    """Store one Work Chats verifier outcome as performance and benchmark signal."""
    builder_session_id = _clean_text(payload.get("builder_session_id"))
    if not builder_session_id:
        raise ValueError("builder_session_id is required")

    benchmark_id = _benchmark_id(payload)
    existing_run = await db.scalar(
        select(AgentBenchmarkRun).where(AgentBenchmarkRun.benchmark_id == benchmark_id)
    )
    if existing_run is not None:
        return VerifierOutcomeResult(
            benchmark_id=benchmark_id,
            benchmark_run_id=existing_run.id,
            performance_log_id=None,
            agent_slug=existing_run.agent_slug,
            model_id=(existing_run.models or ["unknown"])[-1],
            score=int(existing_run.avg_score or 0),
            outcome="existing",
            feedback_type="existing",
            created=False,
        )

    builder = await db.scalar(select(Session).where(Session.id == builder_session_id))
    if builder is None:
        raise LookupError(f"Builder session not found: {builder_session_id}")

    agent_slug = _clean_text(builder.agent_slug) or "unknown"
    model_id = _session_model(builder)
    provider = _session_provider(builder)
    input_tokens, output_tokens = await _cost_totals(db, builder_session_id)
    total_tokens = input_tokens + output_tokens
    label, score = _score(payload)
    outcome, feedback_type = _performance_outcome(label)
    claims, passed_claims, failed_claims = _claim_counts(payload)
    now = datetime.now(UTC)
    case_id = _case_id(payload)
    project_id = _clean_text(payload.get("project_id")) or builder.project_id
    report_excerpt = _clean_text(payload.get("report_excerpt"), limit=5000)
    feedback_loop_count = int(payload.get("feedback_loop_count") or 0)

    performance_log = AgentPerformanceLog(
        agent_slug=agent_slug,
        model_id=model_id,
        task_type="work_chat_verifier",
        project_id=project_id,
        outcome=outcome,
        feedback_type=feedback_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        content=_log_content(
            payload,
            label=label,
            score=score,
            agent_slug=agent_slug,
            model_id=model_id,
        ),
        session_id=builder_session_id,
        logged_by="system",
    )
    db.add(performance_log)

    benchmark_run = AgentBenchmarkRun(
        benchmark_id=benchmark_id,
        agent_slug=agent_slug,
        project_id=project_id,
        suite_id=SUITE_ID,
        run_kind=RUN_KIND,
        status="completed",
        models=[model_id],
        case_ids=[case_id],
        runs_per_case=1,
        use_memory=True,
        avg_score=float(score),
        pass_rate=(passed_claims / claims * 100) if claims else (100.0 if score >= 80 else 0.0),
        attempt_count=1,
        passed_attempt_count=1 if score >= 80 else 0,
        infra_failure_count=0,
        config_snapshot={
            "agent_slug": agent_slug,
            "model_id": model_id,
            "provider": provider,
            "builder_session_id": builder_session_id,
            "parent_session_id": payload.get("parent_session_id"),
            "request_source": builder.request_source,
            "client_id": builder.client_id,
        },
        run_metadata={
            "status": payload.get("status"),
            "confidence": payload.get("confidence"),
            "score_label": label,
            "score": score,
            "parent_session_id": payload.get("parent_session_id"),
            "verifier_session_id": payload.get("verifier_session_id"),
            "builder_session_id": builder_session_id,
            "task_id": payload.get("task_id"),
            "atomic_claim_count": claims,
            "atomic_pass_count": passed_claims,
            "atomic_fail_count": failed_claims,
            "feedback_loop_count": feedback_loop_count,
            "report_excerpt": report_excerpt,
        },
        started_at=now,
        completed_at=now,
    )
    db.add(benchmark_run)
    await db.flush()

    benchmark_attempt = AgentBenchmarkAttempt(
        benchmark_run_id=benchmark_run.id,
        agent_slug=agent_slug,
        model_id=model_id,
        effective_model=model_id,
        requested_model=builder.model,
        case_id=case_id,
        run_number=1,
        session_id=builder_session_id,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        correctness_score=float(score),
        composite_score=float(score),
        passed=score >= 80,
        failure_kind=None if score >= 80 else "verification",
        failure_detail=None if score >= 80 else (report_excerpt or label),
        confidence=label,
        summary=report_excerpt[:1000] or None,
        raw_content=report_excerpt,
    )
    db.add(benchmark_attempt)

    return VerifierOutcomeResult(
        benchmark_id=benchmark_id,
        benchmark_run_id=benchmark_run.id,
        performance_log_id=performance_log.id,
        agent_slug=agent_slug,
        model_id=model_id,
        score=score,
        outcome=outcome,
        feedback_type=feedback_type,
        created=True,
    )
