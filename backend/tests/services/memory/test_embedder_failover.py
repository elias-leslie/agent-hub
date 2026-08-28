"""Tests for Gemini key-pool failover in EmbedderService.

Gemini reports a depleted prepay balance as 429 RESOURCE_EXHAUSTED, so an
account that has been shut off looks exactly like a momentary quota bounce.
Embedding must rotate onto a funded account instead of failing every write.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.llm import api_key_pool
from app.services.memory.embedder import EmbedderService
from app.services.memory.episode_creator_helpers import (
    handle_rate_limit_error,
    is_rate_limit_error,
)

BILLING_ERROR = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'Your prepayment "
    "credits are depleted.', 'status': 'RESOURCE_EXHAUSTED'}}"
)


def _make_embed_result(values: list[float]) -> SimpleNamespace:
    return SimpleNamespace(embeddings=[SimpleNamespace(values=values)])


@pytest.fixture(autouse=True)
def _clear_pool() -> None:
    api_key_pool.reset("gemini")


def _embedder(
    keys: list[str],
    responses: dict[str, object],
    attempts: list[str] | None = None,
) -> EmbedderService:
    """Build an embedder over ``keys`` whose client per key returns/raises.

    ``attempts``, when given, records the keys the service actually tried.
    """
    with patch(
        "app.services.memory.embedder._resolve_gemini_api_keys", return_value=keys
    ):
        svc = EmbedderService()

    def _client_for(api_key: str) -> MagicMock:
        client = MagicMock()
        outcome = responses[api_key]

        async def _embed(**_kwargs: object) -> object:
            if attempts is not None:
                attempts.append(api_key)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        client.aio.models.embed_content = _embed
        return client

    svc._pool_keys = lambda: keys  # type: ignore[method-assign]
    svc._client_for = _client_for  # type: ignore[method-assign]
    return svc


@pytest.mark.asyncio
async def test_embed_rotates_past_depleted_account() -> None:
    svc = _embedder(
        ["dead-key", "funded-key"],
        {
            "dead-key": Exception(BILLING_ERROR),
            "funded-key": _make_embed_result([0.5]),
        },
    )

    assert await svc.embed("hello") == [0.5]


@pytest.mark.asyncio
async def test_depleted_account_is_benched_for_later_calls() -> None:
    svc = _embedder(
        ["dead-key", "funded-key"],
        {
            "dead-key": Exception(BILLING_ERROR),
            "funded-key": _make_embed_result([0.5]),
        },
    )

    await svc.embed("hello")

    # The dead key is on cooldown, so the funded one is tried first from now on.
    assert api_key_pool.ordered_keys("gemini", ["dead-key", "funded-key"])[0] == (
        "funded-key"
    )


@pytest.mark.asyncio
async def test_request_error_does_not_burn_the_pool() -> None:
    """A malformed request fails the same way on every account."""
    boom = ValueError("400 INVALID_ARGUMENT: contents must not be empty")
    attempts: list[str] = []
    svc = _embedder(
        ["key-a", "key-b"],
        {"key-a": boom, "key-b": _make_embed_result([0.9])},
        attempts,
    )

    with pytest.raises(ValueError):
        await svc.embed("hello")

    assert len(attempts) == 1
    assert api_key_pool.classify_key_failure(boom) is None


@pytest.mark.asyncio
async def test_every_account_depleted_raises_last_error() -> None:
    svc = _embedder(
        ["key-a", "key-b"],
        {"key-a": Exception(BILLING_ERROR), "key-b": Exception(BILLING_ERROR)},
    )

    with pytest.raises(Exception, match="prepayment credits are depleted"):
        await svc.embed("hello")


@pytest.mark.asyncio
async def test_embed_batch_rotates_past_depleted_account() -> None:
    svc = _embedder(
        ["dead-key", "funded-key"],
        {
            "dead-key": Exception(BILLING_ERROR),
            "funded-key": SimpleNamespace(
                embeddings=[SimpleNamespace(values=[0.1]), SimpleNamespace(values=[0.2])]
            ),
        },
    )

    assert await svc.embed_batch(["a", "b"]) == [[0.1], [0.2]]


def test_billing_stop_does_not_tell_the_operator_to_wait() -> None:
    error = Exception(BILLING_ERROR)
    assert is_rate_limit_error(error)

    result = handle_rate_limit_error(error)
    detail = result.validation_error or ""

    assert result.success is False
    assert "out of credit" in detail
    assert "Wait a few minutes" not in detail


def test_plain_quota_bounce_still_says_retry() -> None:
    error = Exception("429 RESOURCE_EXHAUSTED: quota exceeded, retry later")

    result = handle_rate_limit_error(error)

    assert "Wait a few minutes and retry" in (result.validation_error or "")
