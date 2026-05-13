"""Persist runtime model/provider health learned from live adapter calls."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

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
    """Compatibility hook after removing runtime routing health tables."""
    _ = (db, model_id, provider)


async def record_model_runtime_failure(
    db: AsyncSession | None,
    *,
    model_id: str,
    provider: str,
    error: BaseException,
) -> RuntimeFailureClassification:
    """Mark a model/provider pair unroutable after a classified live failure."""
    classification = classify_runtime_failure(error)
    _ = (db, model_id, provider)
    return classification


__all__ = [
    "RuntimeFailureClassification",
    "classify_runtime_failure",
    "record_model_runtime_failure",
    "record_model_runtime_success",
]
