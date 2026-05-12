"""Persist runtime model/provider health learned from live adapter calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelAvailability, ProviderEntitlement
from app.services.llm_errors import RateLimitError

_AUTH_MARKERS = ("invalid api key", "unauthorized", "401", "invalid bearer token")
_PROVIDER_QUOTA_MARKERS = (
    "insufficient credits",
    "daily free allocation",
    "used up your daily free allocation",
    "402",
)
_RATE_LIMIT_MARKERS = (
    "429",
    "too many requests",
    "resource_exhausted",
    "quota",
    "rate limit",
)
_NOT_FOUND_MARKERS = ("404", "not found", "model_not_found")


@dataclass(frozen=True)
class RuntimeFailureClassification:
    smoke_status: str
    provider_status: str | None
    routable: bool
    cooldown_seconds: float | None


def classify_runtime_failure(error: BaseException) -> RuntimeFailureClassification:
    """Classify provider runtime errors into routing health decisions."""
    text = str(error).lower()
    if any(marker in text for marker in _PROVIDER_QUOTA_MARKERS):
        return RuntimeFailureClassification(
            smoke_status="quota_or_rate_limited",
            provider_status="quota_exhausted",
            routable=False,
            cooldown_seconds=3600.0,
        )
    if isinstance(error, RateLimitError) or any(marker in text for marker in _RATE_LIMIT_MARKERS):
        return RuntimeFailureClassification(
            smoke_status="quota_or_rate_limited",
            provider_status=None,
            routable=False,
            cooldown_seconds=getattr(error, "retry_after", None) if isinstance(error, RateLimitError) else None,
        )
    if any(marker in text for marker in _AUTH_MARKERS):
        return RuntimeFailureClassification(
            smoke_status="auth_failed",
            provider_status="invalid_credentials",
            routable=False,
            cooldown_seconds=3600.0,
        )
    if any(marker in text for marker in _NOT_FOUND_MARKERS):
        return RuntimeFailureClassification(
            smoke_status="model_not_found",
            provider_status=None,
            routable=False,
            cooldown_seconds=None,
        )
    return RuntimeFailureClassification(
        smoke_status="runtime_error",
        provider_status=None,
        routable=False,
        cooldown_seconds=None,
    )


async def record_model_runtime_success(
    db: AsyncSession | None,
    *,
    model_id: str,
    provider: str,
) -> None:
    """Mark a model/provider pair routable after a successful live call."""
    if db is None:
        return
    row = await _availability_row(db, model_id, provider)
    if row is not None:
        row.routable = row.enabled
        row.last_smoke_status = "runtime_ok"
        row.last_smoke_at = datetime.now(UTC)
        row.failure_reason = None
    entitlement = await _provider_entitlement(db, provider)
    if entitlement is not None and entitlement.status not in {"missing", "disabled"}:
        entitlement.status = "active"
        entitlement.last_verified_at = datetime.now(UTC)
    await db.commit()


async def record_model_runtime_failure(
    db: AsyncSession | None,
    *,
    model_id: str,
    provider: str,
    error: BaseException,
) -> RuntimeFailureClassification:
    """Mark a model/provider pair unroutable after a classified live failure."""
    classification = classify_runtime_failure(error)
    if db is None:
        return classification
    failure_reason = _compact_failure_reason(error)
    row = await _availability_row(db, model_id, provider)
    if row is not None:
        row.routable = classification.routable
        row.last_smoke_status = classification.smoke_status
        row.last_smoke_at = datetime.now(UTC)
        row.failure_reason = failure_reason
    entitlement = await _provider_entitlement(db, provider)
    if entitlement is not None and classification.provider_status is not None:
        entitlement.status = classification.provider_status
        metadata = dict(entitlement.metadata_ or {})
        metadata["last_runtime_failure"] = classification.smoke_status
        entitlement.metadata_ = metadata
        entitlement.last_verified_at = datetime.now(UTC)
    await db.commit()
    return classification


async def _availability_row(
    db: AsyncSession,
    model_id: str,
    provider: str,
) -> ModelAvailability | None:
    return await db.scalar(
        select(ModelAvailability).where(
            ModelAvailability.model_id == model_id,
            ModelAvailability.provider == provider,
        )
    )


async def _provider_entitlement(db: AsyncSession, provider: str) -> ProviderEntitlement | None:
    return await db.scalar(
        select(ProviderEntitlement).where(
            ProviderEntitlement.provider == provider,
            ProviderEntitlement.enabled == True,  # noqa: E712
        )
    )


def _compact_failure_reason(error: BaseException) -> str:
    text = " ".join(str(error).split())
    return text[:500]


__all__ = [
    "RuntimeFailureClassification",
    "classify_runtime_failure",
    "record_model_runtime_failure",
    "record_model_runtime_success",
]
