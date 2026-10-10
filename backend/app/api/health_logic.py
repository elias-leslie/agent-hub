import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.health_schemas import (
    ProviderHealthDetails,
    ProviderStatus,
    StatusResponse,
)

logger = logging.getLogger(__name__)

# Completion outcomes behind provider health: ``POST /api/complete`` rows in
# request_logs (buffered and streaming completions share the endpoint).
OUTCOME_WINDOW = timedelta(hours=24)
COMPLETION_ENDPOINT = "/api/complete"


@dataclass
class ProviderOutcomes:
    calls: int = 0
    failures: int = 0
    latency_total: float = 0.0
    latency_samples: int = 0
    last_call: datetime | None = None
    last_success: datetime | None = None
    last_failure: datetime | None = None
    last_failure_label: str | None = None
    consecutive_failures: int = 0


async def recent_completion_outcomes(
    db: AsyncSession, now: datetime | None = None
) -> dict[str, ProviderOutcomes]:
    """Aggregate recent completion outcomes per provider from request_logs."""
    from app.models import RequestLog
    from app.routing.registry import UNKNOWN_PROVIDER, get_provider_for_model

    cutoff = (now or datetime.now(UTC)) - OUTCOME_WINDOW
    in_window = (
        RequestLog.endpoint == COMPLETION_ENDPOINT,
        RequestLog.method == "POST",
        RequestLog.created_at >= cutoff,
        RequestLog.model.isnot(None),
    )
    # Provider-attributable failure: a 5xx or a 429; other 4xx are caller errors.
    failed = or_(RequestLog.status_code >= 500, RequestLog.status_code == 429)
    per_model = (
        await db.execute(
            select(
                RequestLog.model,
                func.count(RequestLog.id).label("calls"),
                func.sum(case((failed, 1), else_=0)).label("failures"),
                func.sum(RequestLog.latency_ms).label("latency_total"),
                func.count(RequestLog.latency_ms).label("latency_samples"),
                func.max(RequestLog.created_at).label("last_call"),
                func.max(case((~failed, RequestLog.created_at))).label("last_success"),
            )
            .where(*in_window)
            .group_by(RequestLog.model)
        )
    ).all()

    outcomes: dict[str, ProviderOutcomes] = {}
    model_provider: dict[str, str] = {}
    for row in per_model:
        provider = get_provider_for_model(row.model)
        if provider == UNKNOWN_PROVIDER:
            continue
        model_provider[row.model] = provider
        agg = outcomes.setdefault(provider, ProviderOutcomes())
        agg.calls += int(row.calls or 0)
        agg.failures += int(row.failures or 0)
        agg.latency_total += float(row.latency_total or 0)
        agg.latency_samples += int(row.latency_samples or 0)
        agg.last_call = max(filter(None, (agg.last_call, row.last_call)), default=None)
        agg.last_success = max(filter(None, (agg.last_success, row.last_success)), default=None)

    failures = (
        await db.execute(
            select(RequestLog.model, RequestLog.status_code, RequestLog.created_at)
            .where(*in_window, failed)
            .order_by(RequestLog.created_at.desc())
        )
    ).all()
    for row in failures:
        provider = model_provider.get(row.model)
        if provider is None:
            continue
        agg = outcomes[provider]
        if agg.last_failure is None:
            agg.last_failure = row.created_at
            agg.last_failure_label = f"HTTP {row.status_code} from {row.model}"
        if agg.last_success is None or row.created_at > agg.last_success:
            agg.consecutive_failures += 1
    return outcomes


def _health_details(available: bool, outcome: ProviderOutcomes | None) -> ProviderHealthDetails | None:
    if outcome is None or outcome.calls == 0:
        return None
    if not available:
        state = "unavailable"
    elif outcome.consecutive_failures > 0:
        state = "degraded"
    else:
        state = "healthy"
    error_rate = outcome.failures / outcome.calls
    return ProviderHealthDetails(
        state=state,
        latency_ms=outcome.latency_total / outcome.latency_samples if outcome.latency_samples else 0.0,
        error_rate=error_rate,
        availability=1 - error_rate,
        consecutive_failures=outcome.consecutive_failures,
        last_check=outcome.last_call.timestamp() if outcome.last_call else None,
        last_success=outcome.last_success.timestamp() if outcome.last_success else None,
        last_error=outcome.last_failure_label,
    )


async def provider_outcome_report(
    db: AsyncSession | None = None,
) -> list[tuple[ProviderStatus, ProviderOutcomes | None]]:
    """Readiness of each routing provider, paired with its recent completion outcomes.

    Readiness is the same check routing runs before a call. With a database
    session, ``health`` reports the last 24 hours of ``/api/complete`` outcomes
    for that provider; it stays empty when the provider had no calls.
    """
    from app.routing.availability import provider_unavailable_reason
    from app.routing.registry import list_workload_providers

    outcomes: dict[str, ProviderOutcomes] = {}
    if db is not None:
        try:
            outcomes = await recent_completion_outcomes(db)
        except Exception:
            await db.rollback()
            logger.warning("Completion outcome lookup failed; reporting readiness only", exc_info=True)

    report = []
    for provider in list_workload_providers():
        reason = await provider_unavailable_reason(provider)
        available = reason is None
        outcome = outcomes.get(provider)
        status = ProviderStatus(
            name=provider,
            available=available,
            configured=available,
            error=reason,
            health=_health_details(available, outcome),
        )
        report.append((status, outcome))
    return report


async def provider_statuses(db: AsyncSession | None = None) -> list[ProviderStatus]:
    """Provider statuses for ``/api/status`` (see ``provider_outcome_report``)."""
    return [status for status, _ in await provider_outcome_report(db)]


async def _check_database(db: AsyncSession) -> str:
    """Ping the database and return a status string."""
    try:
        await db.execute(text("SELECT 1"))
        return "connected"
    except Exception as e:
        logger.warning(f"Database check failed: {e}")
        return f"error: {str(e)[:50]}"


async def fetch_status(db: AsyncSession, start_time: float) -> StatusResponse:
    """Internal function to fetch fresh status data."""
    db_status = await _check_database(db)
    providers = await provider_statuses(db if db_status == "connected" else None)

    return StatusResponse(
        status="healthy" if db_status == "connected" else "degraded",
        service="agent-hub",
        database=db_status,
        providers=providers,
        uptime_seconds=time.time() - start_time,
    )
