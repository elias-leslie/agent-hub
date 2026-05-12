from __future__ import annotations

from app.services.llm_errors import RateLimitError
from app.services.model_runtime_health import classify_runtime_failure


def test_invalid_key_failure_disables_provider_for_runtime_routing() -> None:
    result = classify_runtime_failure(RuntimeError("Error code: 401 invalid api key"))

    assert result.smoke_status == "auth_failed"
    assert result.provider_status == "invalid_credentials"
    assert result.routable is False
    assert result.cooldown_seconds == 3600.0


def test_quota_failure_disables_provider_with_short_cooldown() -> None:
    result = classify_runtime_failure(RateLimitError(provider="gemini", retry_after=26))

    assert result.smoke_status == "quota_or_rate_limited"
    assert result.provider_status is None
    assert result.routable is False
    assert result.cooldown_seconds == 26


def test_provider_credit_failure_disables_provider() -> None:
    result = classify_runtime_failure(RuntimeError("Error code: 402 insufficient credits"))

    assert result.smoke_status == "quota_or_rate_limited"
    assert result.provider_status == "quota_exhausted"
    assert result.routable is False
    assert result.cooldown_seconds == 3600.0


def test_model_not_found_disables_only_model() -> None:
    result = classify_runtime_failure(RuntimeError("404 model not found"))

    assert result.smoke_status == "model_not_found"
    assert result.provider_status is None
    assert result.routable is False
    assert result.cooldown_seconds is None
