"""Key rotation has to spread load, bench refusals, and stay out of the way."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.llm.api_key_pool import (
    AUTH_COOLDOWN_SECONDS,
    BILLING_COOLDOWN_SECONDS,
    RATE_LIMIT_COOLDOWN_SECONDS,
    classify_key_failure,
    mark_key_failure,
    mark_key_success,
    ordered_keys,
    reset,
)

PROVIDER = "google-test"
KEYS = ["key-a", "key-b", "key-c"]


@pytest.fixture(autouse=True)
def _clean_pool() -> Iterator[None]:
    reset()
    yield
    reset()


def test_rotation_spreads_requests_across_accounts() -> None:
    """Quota is per account, so consecutive calls must not all hit the same key."""
    firsts = [ordered_keys(PROVIDER, KEYS)[0] for _ in range(3)]
    assert sorted(firsts) == sorted(KEYS)


def test_single_key_provider_is_untouched() -> None:
    assert ordered_keys(PROVIDER, ["only"]) == ["only"]
    assert ordered_keys(PROVIDER, []) == []


def test_benched_key_sorts_behind_healthy_keys() -> None:
    mark_key_failure(PROVIDER, "key-a", RuntimeError("429 RESOURCE_EXHAUSTED"))
    for _ in range(len(KEYS)):
        assert ordered_keys(PROVIDER, KEYS)[-1] == "key-a"


def test_all_keys_benched_still_yields_a_candidate() -> None:
    """Failing locally is worse than failing against the API."""
    for key in KEYS:
        mark_key_failure(PROVIDER, key, RuntimeError("429 RESOURCE_EXHAUSTED"))
    assert sorted(ordered_keys(PROVIDER, KEYS)) == sorted(KEYS)


def test_success_clears_a_bench() -> None:
    mark_key_failure(PROVIDER, "key-a", RuntimeError("429 RESOURCE_EXHAUSTED"))
    mark_key_success(PROVIDER, "key-a")
    firsts = {ordered_keys(PROVIDER, KEYS)[0] for _ in range(3)}
    assert "key-a" in firsts


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("429 RESOURCE_EXHAUSTED. rate limit", RATE_LIMIT_COOLDOWN_SECONDS),
        ("429 Your prepayment credits are depleted.", BILLING_COOLDOWN_SECONDS),
        ("400 API key not valid. Please pass a valid API key.", AUTH_COOLDOWN_SECONDS),
        ("403 PERMISSION_DENIED", AUTH_COOLDOWN_SECONDS),
    ],
)
def test_refusals_are_classified_by_how_long_they_last(message: str, expected: float) -> None:
    assert classify_key_failure(RuntimeError(message)) == expected


@pytest.mark.parametrize(
    "message",
    [
        "400 INVALID_ARGUMENT: contents must not be empty",
        "500 INTERNAL",
        "model gemini-9 not found",
    ],
)
def test_non_key_errors_do_not_bench_anything(message: str) -> None:
    """A bad request fails on every key; rotating would just burn the pool."""
    assert classify_key_failure(RuntimeError(message)) is None
    assert mark_key_failure(PROVIDER, "key-a", RuntimeError(message)) is None
